"""Admin endpoint RBAC through the REAL router (Test 7 regression).

A manual tester reported that a member could add/edit/delete/enable/disable
servers from the dashboard. The server-side contracts pinned here drive the real
FastAPI app (create_app), the real session-cookie + CSRF auth chain, and a REAL
database (embedded sqlite, real SQLAlchemy sessions) - only the DB engine is
swapped, never a fake DB and never a direct handler call.

Pinned for every admin endpoint:
  - anonymous (no session)  -> 401
  - member session          -> 403
  - admin session           -> 2xx
  - PUT (no such route)     -> 405
Plus the read/scope contracts: members read servers and their own keys/audit rows,
a member cannot target another user's id when minting keys or reading audit, and
the gateway audits an upstream tool failure as upstream_error (not success).
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from auth.keys import create_api_key
from auth.rbac import hash_password
from db.models import ApiKey, AuditLog, Base, Server, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "admin-router@urumi.local", "password": "admin-router-pass-123"}
MEMBER = {"email": "member-router@urumi.local", "password": "member-router-pass-123"}


@pytest.fixture()
async def harness():
    """Real app + real sqlite DB seeded with an admin, a member and one server."""
    from tests.conftest import sqlite_ready_metadata

    sqlite_ready_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

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
        srv = Server(slug="ro-test", url="http://ro-test.invalid:8000/mcp", auth_type="none", timeout_ms=5000)
        db.add(srv)
        await db.flush()
        # a pre-existing audit row per user for the scope tests
        # (sqlite renders BigInteger as BIGINT, which is not a rowid alias, so the
        # seed supplies explicit ids like production Postgres would autoincrement)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        db.add_all([
            AuditLog(id=1, ts=now, user_id=admin.id, server_slug="woo", tool_exposed_name="woo__list_orders",
                     tool_upstream_name="list_orders", request_id=uuid.uuid4(), duration_ms=1,
                     outcome="success"),
            AuditLog(id=2, ts=now, user_id=member.id, server_slug="time", tool_exposed_name="time__get_current_time",
                     tool_upstream_name="get_current_time", request_id=uuid.uuid4(), duration_ms=1,
                     outcome="success"),
        ])
        _row, raw_member_key = await create_api_key(db, member.id)
        await db.commit()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, {
            "admin_id": str(admin.id),
            "member_id": str(member.id),
            "server_id": str(srv.id),
            "member_key": raw_member_key,
        }
    await engine.dispose()


async def _login(client: httpx.AsyncClient, email: str, password: str) -> dict:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


MUTATING_SERVER_CALLS = [
    ("post", "/api/servers", {"slug": "evil-probe", "url": "http://urumi-demo-time:8000/mcp", "auth_type": "none", "timeout_ms": 5000}),
    ("patch", "/api/servers/{sid}", {"enabled": False}),
    ("post", "/api/servers/{sid}/disable", None),
    ("post", "/api/servers/{sid}/enable", None),
    ("delete", "/api/servers/{sid}", None),
    ("put", "/api/servers/{sid}", {"enabled": False}),
]

MUTATING_USER_CALLS = [
    ("get", "/api/users", None),
    ("post", "/api/users", {"email": "evil@example.test", "password": "evil-pass-123", "role": "admin"}),
    ("delete", "/api/users/{uid}", None),
]


async def _call(client, method: str, path: str, body, headers: dict, ids: dict):
    path = path.format(sid=ids["server_id"], uid=ids["admin_id"])
    return await client.request(method.upper(), path, json=body, headers=headers)


@pytest.mark.asyncio
async def test_anonymous_cannot_reach_admin_endpoints(harness):
    client, ids = harness
    for method, path, body in MUTATING_SERVER_CALLS + MUTATING_USER_CALLS:
        r = await _call(client, method, path, body, {}, ids)
        if method == "put":
            # routing rejects the unknown method before auth runs
            assert r.status_code == 405, f"anonymous PUT {path} -> {r.status_code}"
        else:
            assert r.status_code == 401, f"anonymous {method.upper()} {path} -> {r.status_code}"


@pytest.mark.asyncio
async def test_member_forbidden_on_server_mutations(harness):
    client, ids = harness
    headers = await _login(client, MEMBER["email"], MEMBER["password"])
    for method, path, body in MUTATING_SERVER_CALLS:
        r = await _call(client, method, path, body, headers, ids)
        if method == "put":
            # no PUT route exists: 405, never a silent success
            assert r.status_code == 405, f"member PUT {path} -> {r.status_code}"
            continue
        assert r.status_code == 403, f"member {method.upper()} {path} -> {r.status_code} (expected 403)"
    # nothing was created/modified
    servers = (await client.get("/api/servers")).json()["servers"]
    assert [s["slug"] for s in servers] == ["ro-test"]
    assert servers[0]["enabled"] is True


@pytest.mark.asyncio
async def test_member_forbidden_on_user_management(harness):
    client, ids = harness
    headers = await _login(client, MEMBER["email"], MEMBER["password"])
    for method, path, body in MUTATING_USER_CALLS:
        r = await _call(client, method, path, body, headers, ids)
        assert r.status_code == 403, f"member {method.upper()} {path} -> {r.status_code} (expected 403)"


@pytest.mark.asyncio
async def test_admin_allowed_on_server_mutations(harness):
    client, ids = harness
    headers = await _login(client, ADMIN["email"], ADMIN["password"])
    r = await _call(client, "post", "/api/servers", {**MUTATING_SERVER_CALLS[0][2], "slug": "admin-created"}, headers, ids)
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    ids["server_id"] = new_id  # point the disable/enable/delete probes at the fresh row
    for method, path, body in MUTATING_SERVER_CALLS[1:5]:
        r = await _call(client, method, path, body, headers, ids)
        assert r.status_code in (200, 204), f"admin {method.upper()} {path} -> {r.status_code}"
    servers = (await client.get("/api/servers")).json()["servers"]
    slugs = [s["slug"] for s in servers]
    assert slugs == ["ro-test"]  # the created server was deleted again


@pytest.mark.asyncio
async def test_admin_allowed_on_user_management(harness):
    client, ids = harness
    headers = await _login(client, ADMIN["email"], ADMIN["password"])
    r = await _call(client, "get", "/api/users", None, headers, ids)
    assert r.status_code == 200 and any(u["email"] == MEMBER["email"] for u in r.json()["users"])
    r = await _call(client, "post", "/api/users", {"email": "temp@example.test", "password": "temp-pass-123", "role": "member"}, headers, ids)
    assert r.status_code == 201, r.text
    temp_id = r.json()["id"]
    r = await client.delete(f"/api/users/{temp_id}", headers=headers)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_put_is_not_a_route(harness):
    """PUT never existed under /api/servers: both roles get 405, not a silent success."""
    client, ids = harness
    for email, password in [(MEMBER["email"], MEMBER["password"]), (ADMIN["email"], ADMIN["password"])]:
        headers = await _login(client, email, password)
        r = await _call(client, "put", "/api/servers/{sid}", {"enabled": False}, headers, ids)
        assert r.status_code == 405, f"{email} PUT -> {r.status_code}"


@pytest.mark.asyncio
async def test_member_read_endpoints_allowed(harness):
    client, ids = harness
    headers = await _login(client, MEMBER["email"], MEMBER["password"])
    for path in ["/api/servers", f"/api/servers/{ids['server_id']}", "/api/keys", "/api/me", "/api/tools", "/api/audit"]:
        r = await client.get(path, headers=headers)
        assert r.status_code == 200, f"member GET {path} -> {r.status_code}"


@pytest.mark.asyncio
async def test_member_audit_scope_cannot_target_other_users(harness):
    client, ids = harness
    headers = await _login(client, MEMBER["email"], MEMBER["password"])
    r = await client.get(f"/api/audit?user_id={ids['admin_id']}", headers=headers)
    assert r.status_code == 200
    rows = r.json()["logs"]
    assert rows, "member has one own audit row from the seed"
    assert all(str(row["user_id"]) == ids["member_id"] for row in rows)
    # and the admin filter only applies to admins
    r = await client.get(f"/api/audit?user_id={ids['member_id']}", headers=headers)
    assert all(str(row["user_id"]) == ids["member_id"] for row in r.json()["logs"])


@pytest.mark.asyncio
async def test_member_cannot_mint_key_for_another_user(harness):
    client, ids = harness
    headers = await _login(client, MEMBER["email"], MEMBER["password"])
    r = await client.post("/api/keys", json={"user_id": ids["admin_id"]}, headers=headers)
    assert r.status_code == 201, r.text
    key_id = uuid.UUID(r.json()["id"])
    # the spoofed user_id must be ignored: the row belongs to the member
    # read back through the same dependency the app uses (real DB row)
    from db.session import get_db as _g
    # reaching into the dependency override is the point of this test (private attr
    # on the httpx Transport, not on the code under test)
    override = client._transport.app.dependency_overrides[_g]
    agen = override()
    session = await agen.__anext__()
    try:
        row = (await session.execute(select(ApiKey).where(ApiKey.id == key_id))).scalars().first()
        assert row is not None and row.user_id == uuid.UUID(ids["member_id"])
    finally:
        await agen.aclose()


@pytest.mark.asyncio
async def test_mcp_tools_call_audits_upstream_error(harness, monkeypatch):
    """An upstream tool that ran but failed (isError=true) must audit as
    upstream_error with the stable code, not as success."""
    import routes.mcp as mcp_route

    client, ids = harness
    captured: list[dict] = []

    async def fake_log_audit(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(mcp_route, "log_audit", fake_log_audit)

    async def failing_route(*args, **kwargs):
        return {"content": [{"type": "text", "text": "WOO_AUTH_FAILED: Woo auth failed — check Consumer Key"}], "isError": True}

    monkeypatch.setattr(mcp_route, "call_tool_routed", failing_route)
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "woo__list_orders", "arguments": {}}},
        headers={"Authorization": f"Bearer {ids['member_key']}"},
    )
    assert r.status_code == 200 and r.json()["result"]["isError"] is True
    assert captured and captured[-1]["outcome"] == "upstream_error"
    assert captured[-1]["error_code"] == "WOO_AUTH_FAILED"

    async def ok_route(*args, **kwargs):
        return {"content": [{"type": "text", "text": '{"orders":[]}'}], "isError": False}

    monkeypatch.setattr(mcp_route, "call_tool_routed", ok_route)
    captured.clear()
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "woo__list_orders", "arguments": {}}},
        headers={"Authorization": f"Bearer {ids['member_key']}"},
    )
    assert r.status_code == 200 and r.json()["result"]["isError"] is False
    assert captured and captured[-1]["outcome"] == "success" and captured[-1]["error_code"] is None
