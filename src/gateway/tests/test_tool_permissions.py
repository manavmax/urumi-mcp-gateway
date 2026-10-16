"""Per-role tool permissions (stand-out item 2): member deny rules.

The contract (docs/DECISIONS.md ADR-033):
  - Admins restrict which tools the MEMBER role may use; admins always have all tools.
  - Restricted tools are hidden from tools/list AND rejected if called directly,
    for BOTH the external MCP endpoint (/mcp, real SDK client) and the chat agent.
  - Default policy = allow everything; an empty deny table must not change DoD.
  - ONE enforcement code path in the routing core (gw_mcp/permissions.py), used by
    listing (filter) and calling (check before routing upstream).
  - A denied call never reaches the upstream, writes an audit row with
    outcome=permission_denied under the right user, and returns the standard
    unknown-tool error (no existence leak).
  - Policy changes take effect on the very next call; removing a rule restores the tool.
  - API: GET/PUT /api/permissions (admin only). PUT is CSRF-protected and requires
    admin; members get 403; unknown tool/server gives 422.
"""

from __future__ import annotations

import httpx
import pytest
from auth.keys import create_api_key
from auth.rbac import hash_password
from db.models import Base, Server, Tool, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "perm-admin@urumi.local", "password": "perm-admin-pass-123"}
MEMBER = {"email": "perm-member@urumi.local", "password": "perm-member-pass-123"}

TOOL_ROWS = [
    ("woo", "list_orders", "woo__list_orders"),
    ("woo", "get_order", "woo__get_order"),
    ("woo", "create_product", "woo__create_product"),
    ("woo", "update_order_status", "woo__update_order_status"),
    ("time", "get_current_time", "time__get_current_time"),
]


@pytest.fixture()
async def harness(monkeypatch):
    """Real app + real sqlite DB with admin, member, two servers, and seeded tools.

    Upstream fan-out and proxy calls are monkeypatched: tools/list returns the seeded
    Tool rows (as the real fan-out would), and call_tool_routed counts calls so a test
    can assert a denied call NEVER reaches the upstream.
    """
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
        servers = [Server(slug=s, url=f"http://urumi-{s}.svc.cluster.local:8000/mcp", auth_type="none", timeout_ms=5000)
                   for s in ("woo", "time")]
        db.add_all(servers)
        await db.flush()
        for slug, upstream, exposed in TOOL_ROWS:
            srv = next(s for s in servers if s.slug == slug)
            db.add(Tool(server_id=srv.id, upstream_name=upstream, exposed_name=exposed,
                        description=f"[{slug}] {upstream}", input_schema={"type": "object", "properties": {}}))
        _row, member_key = await create_api_key(db, member.id)
        await db.commit()

    # live upstream calls are impossible here — count instead of executing
    upstream_calls: list[str] = []

    async def fake_call_tool_routed(db, exposed_name, arguments, **kwargs):
        upstream_calls.append(exposed_name)
        return {"content": [{"type": "text", "text": f"proxied {exposed_name}"}], "isError": False}

    async def fake_fanout_list_tools(db, servers, **kwargs):
        tools = []
        for s in servers:
            r = await db.execute(select(Tool).where(Tool.server_id == s.id))
            for row in r.scalars().all():
                tools.append({"name": row.exposed_name, "description": row.description, "inputSchema": row.input_schema})
        return tools, []

    import routes.mcp as mcp_route

    monkeypatch.setattr(mcp_route, "fanout_list_tools", fake_fanout_list_tools)
    # routes.mcp imports call_tool_routed at module top, so patch the module reference
    monkeypatch_target = mcp_route
    monkeypatch.setattr(monkeypatch_target, "call_tool_routed", fake_call_tool_routed)

    # capture audit rows through the real route (log_audit is normally a queue)
    captured_audit: list[dict] = []

    async def fake_log_audit(**kwargs):
        captured_audit.append(kwargs)

    monkeypatch.setattr(mcp_route, "log_audit", fake_log_audit)

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {
            "client": client,
            "ids": {
                "admin_id": str(admin.id),
                "member_id": str(member.id),
                "member_key": member_key,
            },
            "upstream_calls": upstream_calls,
            "audit": captured_audit,
            "db_factory": SessionLocal,
        }
    await engine.dispose()


async def _login(client, email: str, password: str) -> dict:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


async def _put_rules(client, headers, rules):
    return await client.put("/api/permissions", json={"rules": rules}, headers=headers)


def _tool_names(tools: list[dict]) -> set[str]:
    return {t["name"] for t in tools}


async def _mcplist(client, key: str) -> list[dict]:
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["result"]["tools"]


# --------------------------------------------------------------------------- default policy


@pytest.mark.asyncio
async def test_default_policy_member_sees_all_tools(harness):
    """DoD unchanged: with an empty deny table, a member sees every enabled tool."""
    data = harness
    client = data["client"]
    tools = await _mcplist(client, data["ids"]["member_key"])
    assert _tool_names(tools) == {n for _s, _u, n in TOOL_ROWS}


# --------------------------------------------------------------------------- listing filter


@pytest.mark.asyncio
async def test_member_tools_list_excludes_denied_admin_includes_all(harness):
    data = harness
    client = data["client"]
    await _put_rules(client, await _login(client, ADMIN["email"], ADMIN["password"]),
                     [{"server_slug": "woo", "tool_name": "woo__create_product"}])

    member_tools = await _mcplist(client, data["ids"]["member_key"])
    names = _tool_names(member_tools)
    assert "woo__create_product" not in names
    assert "woo__list_orders" in names and "woo__get_order" in names
    assert "time__get_current_time" in names

    # whole-server deny also hides every tool of that server for members
    await _put_rules(client, await _login(client, ADMIN["email"], ADMIN["password"]),
                     [{"server_slug": "time", "tool_name": None}])
    member_tools = await _mcplist(client, data["ids"]["member_key"])
    names = _tool_names(member_tools)
    assert not any(n.startswith("time__") for n in names)
    assert any(n.startswith("woo__") for n in names)

    # admin always sees all tools (admin key minted fresh below)
    async with data["db_factory"]() as db:
        admin = (await db.execute(select(User).where(User.email == ADMIN["email"]))).scalars().first()
        _row, admin_key = await create_api_key(db, admin.id)
        await db.commit()
    admin_tools = await _mcplist(client, admin_key)
    assert _tool_names(admin_tools) == {n for _s, _u, n in TOOL_ROWS}


@pytest.mark.asyncio
async def test_external_mcp_client_real_sdk_obeys_tool_list_policy(harness, monkeypatch):
    """A REAL MCP SDK client (streamablehttp_client + ClientSession) sees the policy:
    tools/list hides the denied tool for a member and shows it for an admin."""
    import socket
    import threading
    import time

    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    data = harness
    app = data["client"]._transport.app

    # Put a deny rule in place first (through the admin API)
    admin_headers = await _login(data["client"], ADMIN["email"], ADMIN["password"])
    await _put_rules(data["client"], admin_headers, [{"server_slug": "woo", "tool_name": "woo__create_product"}])

    # uvicorn must not run the real lifespan (alembic + seed hit the REAL postgres)
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app.router.lifespan_context = _noop_lifespan

    def _free_port():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", loop="asyncio"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("uvicorn did not start")

    try:
        url = f"http://127.0.0.1:{port}/mcp"

        async def _list(url, key):
            async with (
                streamablehttp_client(url, headers={"Authorization": f"Bearer {key}"}) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                listing = await session.list_tools()
                return [t.name for t in listing.tools]

        member_names = await _list(url, data["ids"]["member_key"])
        assert "woo__create_product" not in member_names, member_names
        assert "woo__list_orders" in member_names, member_names

        async with data["db_factory"]() as db:
            admin = (await db.execute(select(User).where(User.email == ADMIN["email"]))).scalars().first()
            _row, admin_key = await create_api_key(db, admin.id)
            await db.commit()
        admin_names = await _list(url, admin_key)
        assert "woo__create_product" in admin_names, admin_names
    finally:
        server.should_exit = True
        t.join(timeout=5)


# --------------------------------------------------------------------------- call enforcement


@pytest.mark.asyncio
async def test_member_direct_call_to_denied_tool_rejected_never_upstream_and_audits(harness):
    """A member calling a denied tool: rejected (standard unknown-tool error), zero
    upstream calls, permission_denied audit row under the member."""
    data = harness
    client = data["client"]
    member_id = data["ids"]["member_id"]
    await _put_rules(client, await _login(client, ADMIN["email"], ADMIN["password"]),
                     [{"server_slug": "woo", "tool_name": "woo__create_product"}])

    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 5, "method": "tools/call",
              "params": {"name": "woo__create_product", "arguments": {}}},
        headers={"Authorization": f"Bearer {data['ids']['member_key']}"},
    )
    assert r.status_code in (400, 403), r.text
    err = r.json()["error"]
    # standard unknown-tool error shape, no existence leak ("Unknown tool")
    assert err["code"] == -32602 or "Unknown tool" in err.get("message", "") or "permission denied" in err.get("message", ""), err
    # never reaches a mocked upstream
    assert data["upstream_calls"] == [], f"denied call reached upstream: {data['upstream_calls']}"
    # permission_denied audit row under the right user
    assert data["audit"], "no audit row written"
    denied_rows = [a for a in data["audit"] if a["outcome"] == "permission_denied"]
    assert denied_rows, f"no permission_denied audit row: {data['audit']}"
    assert str(denied_rows[-1]["user_id"]) == member_id
    assert denied_rows[-1]["tool_exposed_name"] == "woo__create_product"


@pytest.mark.asyncio
async def test_admin_can_call_any_tool_including_denied_ones(harness):
    """Admins always have all tools: an admin key can call a member-denied tool."""
    data = harness
    client = data["client"]
    await _put_rules(client, await _login(client, ADMIN["email"], ADMIN["password"]),
                     [{"tool_name": "woo__create_product", "server_slug": "woo"}])
    async with data["db_factory"]() as db:
        admin = (await db.execute(select(User).where(User.email == ADMIN["email"]))).scalars().first()
        _row, admin_key = await create_api_key(db, admin.id)
        await db.commit()
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 6, "method": "tools/call",
              "params": {"name": "woo__create_product", "arguments": {}}},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert r.status_code == 200, r.text
    assert data["upstream_calls"] == ["woo__create_product"]


@pytest.mark.asyncio
async def test_policy_change_applies_on_next_call_removal_restores(harness):
    """No caching: a rule added takes effect on the very next call, and removing the
    rule restores the tool — all without reloading anything."""
    data = harness
    client = data["client"]
    member_key = data["ids"]["member_key"]
    admin_headers = await _login(client, ADMIN["email"], ADMIN["password"])

    # before: allowed
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 7, "method": "tools/call",
              "params": {"name": "woo__create_product", "arguments": {}}},
        headers={"Authorization": f"Bearer {member_key}"},
    )
    assert r.status_code == 200, r.text
    assert data["upstream_calls"] == ["woo__create_product"]

    # add the rule -> next call rejected, no upstream
    await _put_rules(client, admin_headers, [{"server_slug": "woo", "tool_name": "woo__create_product"}])
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 8, "method": "tools/call",
              "params": {"name": "woo__create_product", "arguments": {}}},
        headers={"Authorization": f"Bearer {member_key}"},
    )
    assert r.status_code in (400, 403), r.text
    assert data["upstream_calls"] == ["woo__create_product"], "upstream must not be called after deny"

    # remove the rule -> tool works again on the next call
    await _put_rules(client, admin_headers, [])
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 9, "method": "tools/call",
              "params": {"name": "woo__create_product", "arguments": {}}},
        headers={"Authorization": f"Bearer {member_key}"},
    )
    assert r.status_code == 200, r.text
    assert data["upstream_calls"] == ["woo__create_product", "woo__create_product"]


# --------------------------------------------------------------------------- API RBAC / validation


@pytest.mark.asyncio
async def test_put_permissions_member_forbidden(harness):
    data = harness
    client = data["client"]
    headers = await _login(client, MEMBER["email"], MEMBER["password"])
    r = await _put_rules(client, headers, [{"server_slug": "woo", "tool_name": "woo__create_product"}])
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_put_permissions_requires_csrf(harness):
    data = harness
    client = data["client"]
    # valid admin session but NO csrf header
    await _login(client, ADMIN["email"], ADMIN["password"])
    r = await client.put("/api/permissions", json={"rules": []})
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_put_permissions_unknown_server_or_tool_422(harness):
    data = harness
    client = data["client"]
    admin_headers = await _login(client, ADMIN["email"], ADMIN["password"])
    # unknown server slug
    r = await _put_rules(client, admin_headers, [{"server_slug": "nope", "tool_name": None}])
    assert r.status_code == 422, r.text
    # known server but unknown tool
    r = await _put_rules(client, admin_headers, [{"server_slug": "woo", "tool_name": "woo__does_not_exist"}])
    assert r.status_code == 422, r.text
    # a tool that exists on another server must be rejected too
    r = await _put_rules(client, admin_headers, [{"server_slug": "time", "tool_name": "woo__list_orders"}])
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_get_permissions_admin_ok_member_forbidden(harness):
    data = harness
    client = data["client"]
    # member -> 403
    member_headers = await _login(client, MEMBER["email"], MEMBER["password"])
    r = await client.get("/api/permissions", headers=member_headers)
    assert r.status_code == 403, r.text
    # admin -> 200 with servers + tools grouped, restricted flags, count
    admin_headers = await _login(client, ADMIN["email"], ADMIN["password"])
    r = await client.get("/api/permissions", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "servers" in body and "restricted_count" in body
    by_slug = {s["slug"]: s for s in body["servers"]}
    woo = by_slug["woo"]
    names = [t["name"] for t in woo["tools"]]
    assert "woo__create_product" in names and "woo__list_orders" in names


@pytest.mark.asyncio
async def test_put_permissions_roundtrip_updates_get(harness):
    data = harness
    client = data["client"]
    admin_headers = await _login(client, ADMIN["email"], ADMIN["password"])
    r = await _put_rules(client, admin_headers, [
        {"server_slug": "woo", "tool_name": "woo__create_product"},
        {"server_slug": "woo", "tool_name": "woo__update_order_status"},
    ])
    assert r.status_code == 200, r.text
    assert r.json()["restricted_count"] == 2

    g = await client.get("/api/permissions", headers=admin_headers)
    assert g.status_code == 200, g.text
    by_slug = {s["slug"]: s for s in g.json()["servers"]}
    denied = [t["name"] for t in by_slug["woo"]["tools"] if t["member_denied"]]
    assert denied == ["woo__create_product", "woo__update_order_status"], denied
    assert g.json()["restricted_count"] == 2, g.json()


@pytest.mark.asyncio
async def test_whole_server_deny_is_reflected_in_get(harness):
    data = harness
    client = data["client"]
    admin_headers = await _login(client, ADMIN["email"], ADMIN["password"])
    r = await _put_rules(client, admin_headers, [{"server_slug": "time", "tool_name": None}])
    assert r.status_code == 200, r.text
    g = await client.get("/api/permissions", headers=admin_headers)
    assert g.status_code == 200, g.text
    by_slug = {s["slug"]: s for s in g.json()["servers"]}
    assert all(t["member_denied"] for t in by_slug["time"]["tools"]), by_slug["time"]["tools"]


# --------------------------------------------------------------------------- dialect guard

def test_tool_permissions_ddl_is_postgres_valid():
    """The CHECK constraint must be valid Postgres.

    SQLite tolerates a trailing comma in `IN ('member',)` but Postgres rejects it
    (asyncpg ProgrammingError, syntax error at or near ')'). The unit suite runs on
    SQLite, so it cannot catch that; compile the table DDL with the postgres dialect
    and assert the constraint text is PG-parseable.

    Order-independent: conftest's `sqlite_ready_metadata()` strips every CHECK from
    the SHARED Base.metadata in place, so rebuild the table from the model's own
    `__table_args__` (the source of truth) rather than the mutated metadata.
    """
    from db.models import Base, ToolPermission
    from sqlalchemy import CheckConstraint, MetaData
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    args = ToolPermission.__table_args__ or ()
    model_constraints = [c for c in args if isinstance(c, CheckConstraint)]
    assert model_constraints, "ToolPermission must define a role CHECK constraint"

    # clone ALL tables so the FK to users.id resolves at compile time
    new_meta = MetaData()
    for tbl in list(Base.metadata.tables.values()):
        tbl.to_metadata(new_meta)
    table = new_meta.tables[ToolPermission.__tablename__]
    # the clone may already carry the CHECK (when sqlite_ready_metadata has not run
    # yet): drop existing CHECKs so the model's is added exactly once
    table.constraints = {c for c in table.constraints if not isinstance(c, CheckConstraint)}
    for c in model_constraints:
        table.append_constraint(c)

    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    # the CHECK must be a well-formed IN list, not IN ('member',)
    assert ddl.count("ck_tool_permissions_role") == 1, ddl
    assert "role IN ('member')" in ddl, ddl
    assert "('member',)" not in ddl, ddl
    # whole-server deny relies on a nullable tool_name
    assert "tool_name TEXT" in ddl, ddl
