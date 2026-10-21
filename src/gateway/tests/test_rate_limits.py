"""Per-key and per-user rate limits backed by Postgres counters (ADR-057).

Pins:
  1. the atomic minute-window upsert never loses increments under concurrency,
  2. the per-KEY default limit rejects with a 429 + Retry-After + MCP message
     and audits outcome=rate_limited,
  3. an admin per-key OVERRIDE (PATCH /api/keys/{id}) replaces the default
     (member 403, validation rejects 0/negative),
  4. the per-USER limit spans every key of the user,
  5. chat tool calls count against the same user budget,
  6. a broken counter fails OPEN (calls allowed, warning logged).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import auth.rate_limit as rl
import httpx
import pytest
import routes.mcp as mcp_route
from auth.keys import create_api_key
from auth.rbac import hash_password
from db.models import Base, RateLimitCounter, Server, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "admin-rl@urumi.local", "password": "admin-rl-pass-123"}
MEMBER = {"email": "member-rl@urumi.local", "password": "member-rl-pass-123"}


def fake_settings(*, per_key: int = 60, per_user: int = 240):
    return SimpleNamespace(rate_limit_per_minute=per_key, rate_limit_user_per_minute=per_user)


@pytest.fixture()
async def harness(monkeypatch):
    from tests.conftest import sqlite_ready_metadata

    sqlite_ready_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    # the limiter opens its OWN sessions: point it at the test engine
    monkeypatch.setattr("db.session.get_session_factory", lambda: SessionLocal)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with SessionLocal() as db:
        admin = User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin")
        member = User(email=MEMBER["email"], password_hash=await hash_password(MEMBER["password"]), role="member")
        db.add_all([admin, member])
        await db.flush()
        srv = Server(slug="notes", url="http://notes.invalid:8000/mcp", auth_type="none", timeout_ms=5000)
        db.add(srv)
        await db.flush()
        _r1, admin_key = await create_api_key(db, admin.id)
        r2, member_key = await create_api_key(db, member.id)
        r3, member_key2 = await create_api_key(db, member.id)
        rows = (await db.execute(select(User))).scalars().all()
        by_email = {u.email: u for u in rows}
        await db.commit()
        ids = {
            "admin_id": str(by_email[ADMIN["email"]].id),
            "member_id": str(by_email[MEMBER["email"]].id),
        }

    # member tools can route to a fake upstream
    async def ok_routed(db, name, args, timeout_seconds=None):
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    monkeypatch.setattr(mcp_route, "call_tool_routed", ok_routed)
    captured: list[dict] = []

    async def fake_log_audit(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(mcp_route, "log_audit", fake_log_audit)

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, {"admin_key": admin_key, "member_key": member_key, "member_key2": member_key2,
                       "member_key_id": str(r2.id), "member_key2_id": str(r3.id), **ids}, captured, SessionLocal
    await engine.dispose()


async def _call(client, key, name="notes__list_notes", args=None):
    return await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}},
        headers={"Authorization": f"Bearer {key}"},
    )


@pytest.mark.asyncio
async def test_atomic_counter_no_lost_updates(harness, monkeypatch):
    """50 concurrent consumptions must produce exactly 50 in the counter row."""
    _client, ids, _captured, SessionLocal = harness
    monkeypatch.setattr(rl, "get_settings", lambda: fake_settings(per_key=1000, per_user=1000))
    results = await asyncio.gather(*[
        rl.consume_and_check(user_id=ids["member_id"]) for _ in range(50)
    ])
    assert all(allowed for allowed, _reason, _retry in results)
    async with SessionLocal() as db:
        row = (await db.execute(select(RateLimitCounter).where(RateLimitCounter.scope == f"user:{ids['member_id']}"))).scalars().one()
        assert row.count == 50, f"lost updates: counter={row.count}"


@pytest.mark.asyncio
async def test_per_key_default_limit_rejects_and_audits(harness, monkeypatch):
    client, ids, captured, _db = harness
    monkeypatch.setattr(rl, "get_settings", lambda: fake_settings(per_key=2, per_user=1000))
    # both keys belong to different users; use the member's second key to
    # isolate the KEY limit from the user limit
    for i in range(2):
        r = await _call(client, ids["member_key2"])
        assert r.status_code == 200, f"call {i}: {r.status_code}"
    r = await _call(client, ids["member_key2"])
    assert r.status_code == 429
    assert r.headers.get("retry-after", "").isdigit()
    assert "rate limit exceeded" in r.json()["error"]["message"]
    assert captured, "rate-limited call was not audited"
    rl_rows = [c for c in captured if c.get("outcome") == "rate_limited"]
    assert rl_rows, f"no rate_limited audit row: {captured[-1] if captured else None}"
    assert rl_rows[-1]["error_code"] == "rate_limited_key"


@pytest.mark.asyncio
async def test_admin_override_replaces_default(harness, monkeypatch):
    client, ids, _captured, _db = harness
    # login as admin
    r = await client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert r.status_code == 200
    headers = {"X-CSRF-Token": r.json()["csrf_token"]}
    target_id = ids["member_key_id"]
    r = await client.get("/api/keys", headers=headers)
    target = next(k for k in r.json()["keys"] if k["id"] == target_id)
    assert target["rate_limit_per_minute"] is None  # default state

    # set an override of 3 via PATCH
    r = await client.patch(f"/api/keys/{target_id}", json={"rate_limit_per_minute": 3}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["rate_limit_per_minute"] == 3

    # the override governs even though the default is high
    monkeypatch.setattr(rl, "get_settings", lambda: fake_settings(per_key=1000, per_user=1000))
    for _ in range(3):
        r = await _call(client, ids["member_key"])
        assert r.status_code == 200
    r = await _call(client, ids["member_key"])
    assert r.status_code == 429
    assert "key limit" in r.json()["error"]["message"]

    # clear back to default with null
    r = await client.patch(f"/api/keys/{target_id}", json={"rate_limit_per_minute": None}, headers=headers)
    assert r.status_code == 200
    assert r.json()["rate_limit_per_minute"] is None
    r = await _call(client, ids["member_key"])
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_override_validation_and_permissions(harness):
    client, ids, _captured, _db = harness
    r = await client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    admin_headers = {"X-CSRF-Token": r.json()["csrf_token"]}
    target_id = ids["member_key_id"]

    # 0 and negative limits are rejected (a zero would brick the key)
    for bad in (0, -5):
        r = await client.patch(f"/api/keys/{target_id}", json={"rate_limit_per_minute": bad}, headers=admin_headers)
        assert r.status_code == 422, f"limit {bad} accepted"

    # members cannot set overrides
    r = await client.post("/api/auth/login", json={"email": MEMBER["email"], "password": MEMBER["password"]})
    member_headers = {"X-CSRF-Token": r.json()["csrf_token"]}
    r = await client.patch(f"/api/keys/{target_id}", json={"rate_limit_per_minute": 99}, headers=member_headers)
    assert r.status_code == 403

    # CSRF is enforced
    r = await client.patch(f"/api/keys/{target_id}", json={"rate_limit_per_minute": 99}, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code in (403, 401)


@pytest.mark.asyncio
async def test_per_user_limit_spans_keys(harness, monkeypatch):
    """The user budget is shared across every key: two keys x 2 calls, the 5th
    call on EITHER key trips the user limit."""
    client, ids, _captured, _db = harness
    monkeypatch.setattr(rl, "get_settings", lambda: fake_settings(per_key=1000, per_user=3))
    for key in (ids["member_key"], ids["member_key2"], ids["member_key"]):
        r = await _call(client, key)
        assert r.status_code == 200, r.status_code
    r = await _call(client, ids["member_key2"])
    assert r.status_code == 429
    assert "user limit" in r.json()["error"]["message"]
    # another user is unaffected
    r = await _call(client, ids["admin_key"])
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_broken_counter_fails_open(harness, monkeypatch):
    """The fail-open lives INSIDE consume_and_check: a DB-level failure lets the
    call through (an availability bug beats a false 429)."""
    client, ids, _captured, _db = harness

    async def broken_consume(db, scope, window):
        raise RuntimeError("counter db exploded")

    monkeypatch.setattr(rl, "_consume", broken_consume)
    r = await _call(client, ids["member_key"])
    assert r.status_code == 200, "a broken counter must not reject honest callers"


@pytest.mark.asyncio
async def test_chat_tool_calls_count_against_user_budget(monkeypatch):
    """The chat agent's tool calls consume the same user counter (ADR-057)."""

    from tests.conftest import (
        chat_user,
        install_fake_openai,
        patch_chat_agent,
        text_response,
        tool_call_response,
    )

    calls_seen: list[str] = []

    async def route(db, name, args, timeout_seconds=None):
        calls_seen.append(name)
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    class _S:
        openai_api_key = "test-key-not-real"
        openai_base_url = None
        openai_model = "fake-model-a"
        openai_models = ""
        rate_limit_user_per_minute = 1
        compact_threshold = 0  # ADR-058: auto-compact off in this test

        def model_chain(self):
            return ["fake-model-a"]

        def max_models_per_turn(self):
            return 6

    settings = _S()
    tools = [{"name": "notes__list_notes", "description": "d", "inputSchema": {"type": "object", "properties": {}}}]

    # 1st turn: tool call allowed (budget 1)
    seq1 = [tool_call_response("notes__list_notes"), text_response("done-one")]

    async def create1(*_a, **_kw):
        return seq1.pop(0)

    agent1 = patch_chat_agent(monkeypatch, settings=settings, tools=tools, route=route)
    install_fake_openai(monkeypatch, create1)

    class _DB:
        async def execute(self, stmt):
            class _Res:
                def scalar_one_or_none(self):
                    return "00000000-0000-0000-0000-00000000000a"

            return _Res()

        async def commit(self):
            pass

    # point the limiter at a throwaway in-memory engine
    from tests.conftest import sqlite_ready_metadata

    sqlite_ready_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("db.session.get_session_factory", lambda: SessionLocal)
    monkeypatch.setattr(rl, "get_settings", lambda: settings)

    events: list[dict] = []
    async for evt in agent1.chat_loop(_DB(), chat_user(), [{"role": "user", "content": "list notes"}], "req-1"):
        events.append(evt)
    assert calls_seen == ["notes__list_notes"], calls_seen

    # 2nd turn: the SAME user's budget is exhausted -> tool call is rate_limited
    calls_seen.clear()
    seq2 = [tool_call_response("notes__list_notes"), text_response("done-two")]

    async def create2(*_a, **_kw):
        return seq2.pop(0)

    install_fake_openai(monkeypatch, create2)
    events2: list[dict] = []
    async for evt in agent1.chat_loop(_DB(), chat_user(), [{"role": "user", "content": "again"}], "req-2"):
        events2.append(evt)
    assert calls_seen == [], "the rate-limited tool call must never reach routing"
    tool_events = [e for e in events2 if e.get("type") == "tool_call"]
    assert tool_events and tool_events[0]["outcome"] == "rate_limited", tool_events
    await engine.dispose()
