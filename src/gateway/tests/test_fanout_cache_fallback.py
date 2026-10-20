"""tools/list must not lose a server's tools when one upstream fetch fails (fanout fix).

Defect (problem C in the permissions round): fanout_list_tools merged ONLY the
servers that answered within the timeout. One slow upstream (the demo notes server
under cluster CPU pressure) or an open circuit breaker silently dropped its tools
from every tools/list response, so an external MCP client (Cursor) saw 10 of 13
tools although nothing was restricted and the dashboard showed the server
Connected. Member and admin were affected alike - the difference between the two
keys in the live repro was only WHICH request happened to hit a timeout.

The fix: a server whose live fetch fails (or whose breaker is open) contributes
its last-known cached tools - the tools table is kept warm by the health loop -
and the merged warnings carry stale_cache: True. RBAC filtering still applies to
the stale tools, and nothing is invented for a server that has no cached rows.

These tests run the REAL fanout_list_tools (only fetch_and_cache_tools is
monkeypatched: it raises for the failing servers and returns the seeded rows for
healthy ones, since no network exists in unit tests).
"""

from __future__ import annotations

import httpx
import pytest
from auth.keys import create_api_key
from auth.rbac import hash_password
from db.models import Base, Server, Tool, User
from db.session import get_db
from gw_mcp.breaker import breaker
from httpx import ASGITransport
from main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "fanout-admin@urumi.local", "password": "fanout-admin-pass-123"}
MEMBER = {"email": "fanout-member@urumi.local", "password": "fanout-member-pass-123"}

# slug -> [(upstream, exposed)]; "ghost" is a server with NO cached tool rows
SEED = {
    "notes": [
        ("create_note", "notes__create_note"),
        ("list_notes", "notes__list_notes"),
        ("search_notes", "notes__search_notes"),
    ],
    "time": [
        ("get_current_time", "time__get_current_time"),
        ("convert_time", "time__convert_time"),
    ],
    "woo": [("list_orders", "woo__list_orders"), ("create_product", "woo__create_product")],
}
ALL_EXPOSED = {exposed for tools in SEED.values() for _u, exposed in tools}


@pytest.fixture()
async def fallback_harness(monkeypatch):
    """Real app + real sqlite DB; the notes upstream always times out and the
    ghost upstream (which never cached any tools) always refuses the connection."""
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
        member = User(email=MEMBER["email"], password_hash="x", role="member", is_active=True)
        db.add_all([admin, member])
        await db.flush()
        servers = [Server(slug=s, url=f"http://urumi-{s}.svc.cluster.local:8000/mcp", auth_type="none", timeout_ms=5000)
                   for s in ("notes", "time", "woo", "ghost")]
        db.add_all(servers)
        await db.flush()
        for slug, tools in SEED.items():
            srv = next(x for x in servers if x.slug == slug)
            for upstream, exposed in tools:
                db.add(Tool(server_id=srv.id, upstream_name=upstream, exposed_name=exposed,
                            description=f"[{slug}] {upstream}", input_schema={"type": "object", "properties": {}}))
        _row, member_key = await create_api_key(db, member.id)
        await db.commit()

    async def fake_fetch_and_cache_tools(db, s, timeout_seconds=8.0, **kwargs):
        if s.slug == "notes":
            raise TimeoutError()
        if s.slug == "ghost":
            raise ConnectionRefusedError("connection refused")
        # healthy upstream: serve the already-seeded cache rows (no network here)
        r = await db.execute(select(Tool).where(Tool.server_id == s.id))
        return list(r.scalars().all())

    import gw_mcp.aggregator as aggregator

    monkeypatch.setattr(aggregator, "fetch_and_cache_tools", fake_fetch_and_cache_tools)

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {
            "client": client,
            "member_key": member_key,
            "db_factory": SessionLocal,
            "server_ids": {s.slug: s.id for s in servers},
        }
    await engine.dispose()


async def _admin_key(data) -> str:
    async with data["db_factory"]() as db:
        admin = (await db.execute(select(User).where(User.email == ADMIN["email"]))).scalars().first()
        _row, key = await create_api_key(db, admin.id)
        await db.commit()
    return key


async def _mcplist(client: httpx.AsyncClient, key: str):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    names = sorted(t["name"] for t in result["tools"])
    warnings = result.get("_meta", {}).get("warnings", [])
    return names, warnings


# --------------------------------------------------------------------------- fallback serves cache


@pytest.mark.asyncio
async def test_single_upstream_failure_still_lists_all_tools_for_every_role(fallback_harness):
    """notes fetch times out: its 3 cached tools are STILL listed, for a member and
    an admin alike, and the warning marks them as served from stale cache."""
    data = fallback_harness
    for key in (data["member_key"], await _admin_key(data)):
        names, warnings = await _mcplist(data["client"], key)
        assert set(names) == ALL_EXPOSED, names
        stale = [w for w in warnings if w.get("stale_cache")]
        assert stale and stale[0]["server"] == "notes", warnings
        assert stale[0].get("error"), warnings


@pytest.mark.asyncio
async def test_member_and_admin_see_same_count_when_nothing_restricted(fallback_harness):
    """The exact live symptom: member key vs admin key with an empty deny table.
    Both must list the same full set even though one upstream fails every time."""
    data = fallback_harness
    member_names, _ = await _mcplist(data["client"], data["member_key"])
    admin_names, _ = await _mcplist(data["client"], await _admin_key(data))
    assert set(member_names) == set(admin_names) == ALL_EXPOSED


@pytest.mark.asyncio
async def test_no_cached_rows_still_reports_plain_warning_without_invention(fallback_harness):
    """A failed upstream with NO cached rows must not gain phantom tools: plain
    error warning, exactly as before the fix."""
    data = fallback_harness
    names, warnings = await _mcplist(data["client"], data["member_key"])
    ghost = [w for w in warnings if w.get("server") == "ghost"]
    assert len(ghost) == 1, warnings
    assert ghost[0].get("error"), warnings
    assert "stale_cache" not in ghost[0], warnings
    assert not any(n.startswith("ghost__") for n in names), names


# --------------------------------------------------------------------------- RBAC still applies to stale tools


@pytest.mark.asyncio
async def test_rbac_deny_still_applies_to_stale_cache_tools(fallback_harness):
    """The stale-cache fallback must not bypass the deny policy: a member with a
    deny rule loses the tool from the stale list too, and a direct tools/call of
    it is still rejected, while the admin keeps seeing it."""
    data = fallback_harness
    client = data["client"]

    # deny one notes tool through the admin API
    r = await client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    csrf = {"X-CSRF-Token": r.json()["csrf_token"]}
    r = await client.put("/api/permissions",
                         json={"rules": [{"server_slug": "notes", "tool_name": "notes__create_note"}]},
                         headers=csrf)
    assert r.status_code == 200, r.text

    member_names, warnings = await _mcplist(client, data["member_key"])
    assert "notes__create_note" not in member_names, member_names
    assert len(member_names) == 6, member_names
    # the other notes tools are still there - served from the stale cache
    assert {"notes__list_notes", "notes__search_notes"} <= set(member_names)
    assert any(w.get("stale_cache") and w.get("server") == "notes" for w in warnings), warnings

    # enforcement is independent of the listing source: a direct member call of
    # the denied tool stays rejected even while notes is served from cache
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 5, "method": "tools/call",
              "params": {"name": "notes__create_note", "arguments": {}}},
        headers={"Authorization": f"Bearer {data['member_key']}"},
    )
    assert r.status_code in (400, 403), r.text
    assert "unknown tool" in r.json()["error"]["message"].lower(), r.json()

    # admin unchanged: full list, stale cache does not hide anything
    admin_names, _ = await _mcplist(client, await _admin_key(data))
    assert set(admin_names) == ALL_EXPOSED


@pytest.mark.asyncio
async def test_open_breaker_falls_back_to_cached_tools(fallback_harness):
    """An open circuit breaker no longer hides a server's tools: the cached rows
    are served with a stale_cache warning naming the open circuit."""
    data = fallback_harness
    time_id = data["server_ids"]["time"]
    for _ in range(breaker.failure_threshold):
        breaker.record_failure(time_id)
    assert breaker.is_open(time_id)

    names, warnings = await _mcplist(data["client"], data["member_key"])
    assert set(names) == ALL_EXPOSED, names
    stale = [w for w in warnings if w.get("stale_cache") and w.get("server") == "time"]
    assert len(stale) == 1 and "circuit" in stale[0]["error"], warnings
