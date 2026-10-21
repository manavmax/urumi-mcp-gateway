"""Compact mode: two meta tools over a large catalogue (Phase 3, ADR-058).

Pins:
  1. mode selection (X-Gateway-Mode header or ?mode=compact); default unchanged,
  2. compact tools/list returns EXACTLY the two meta tools,
  3. gateway__search_tools ranks name hits over description hits, honours the
     limit, and respects role permissions (denied tools are unsearchable),
  4. gateway__call_tool routes through the SAME permission/routing/audit code:
     the audit row carries the REAL tool name; a denied inner tool gets the
     standard unknown-tool error + permission_denied audit; meta-in-meta and
     malformed arguments are rejected,
  5. 300 synthetic tools across 10 fake upstreams: compact tools/list is ~an
     order of magnitude smaller than the full list (sizes printed),
  6. the chat agent auto-switches above compactThreshold and routes
     gateway__call_tool to the real tool, audited under the real name.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import routes.mcp as mcp_route
from auth.keys import create_api_key
from auth.rbac import hash_password
from db.models import Base, Server, Tool, ToolPermission, User
from db.session import get_db
from gw_mcp.compact import search_tools
from httpx import ASGITransport
from main import create_app
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "admin-cm@urumi.local", "password": "admin-cm-pass-123"}
MEMBER = {"email": "member-cm@urumi.local", "password": "member-cm-pass-123"}


@pytest.fixture()
async def harness(monkeypatch):
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
        srv = Server(slug="notes", url="http://notes.invalid:8000/mcp", auth_type="none", timeout_ms=5000)
        db.add(srv)
        await db.flush()
        for name, desc in [
            ("list_notes", "List saved notes with optional search"),
            ("create_note", "Create a new note with a title and body"),
            ("search_notes", "Full-text search across notes"),
        ]:
            db.add(Tool(server_id=srv.id, upstream_name=name, exposed_name=f"notes__{name}",
                        description=desc, input_schema={"type": "object", "properties": {}}))
        # member deny rule: search_notes is hidden from members (ADR-033 core)
        db.add(ToolPermission(role="member", server_slug="notes", tool_name="notes__search_notes"))
        _r1, admin_key = await create_api_key(db, admin.id)
        _r2, member_key = await create_api_key(db, member.id)
        await db.commit()

    async def ok_routed(db, name, args, timeout_seconds=None):
        return {"content": [{"type": "text", "text": f"ran {name}"}], "isError": False}

    monkeypatch.setattr(mcp_route, "call_tool_routed", ok_routed)
    captured: list[dict] = []

    async def fake_log_audit(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(mcp_route, "log_audit", fake_log_audit)

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, {"admin_key": admin_key, "member_key": member_key}, captured
    await engine.dispose()


async def _rpc(client, key, method, params=None, *, mode_header=None, mode_query=None):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if mode_header:
        headers["X-Gateway-Mode"] = mode_header
    path = "/mcp" + (f"?mode={mode_query}" if mode_query else "")
    return await client.post(
        path,
        json={"jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params else {})},
        headers=headers,
    )


def _tools(response: httpx.Response) -> list[dict]:
    return response.json()["result"]["tools"]


def _result_text(response: httpx.Response) -> str:
    for block in response.json()["result"]["content"]:
        if block.get("type") == "text":
            return block.get("text", "")
    return ""


# ---- mode selection + tools/list shape ----------------------------------------------


@pytest.mark.asyncio
async def test_compact_selected_by_header_or_query(harness):
    client, keys, _c = harness
    for kwargs in ({"mode_header": "compact"}, {"mode_query": "compact"}):
        r = await _rpc(client, keys["admin_key"], "tools/list", **kwargs)
        names = [t["name"] for t in _tools(r)]
        assert names == ["gateway__search_tools", "gateway__call_tool"], (kwargs, names)
    # default mode unchanged: the full (RBAC-filtered) catalogue
    r = await _rpc(client, keys["admin_key"], "tools/list")
    names = {t["name"] for t in _tools(r)}
    assert "gateway__search_tools" not in names
    assert "notes__list_notes" in names


@pytest.mark.asyncio
async def test_default_mode_rejects_meta_tool_calls(harness, monkeypatch):
    """In default mode the meta names are not special: they fall through to the
    unknown-slug validation error, exactly as before ADR-058."""
    client, keys, _c = harness
    # this test needs the REAL router (the harness stubs it for other tests):
    # the unknown slug is raised by call_tool_routed itself
    from gw_mcp.router import call_tool_routed as real_routed

    monkeypatch.setattr(mcp_route, "call_tool_routed", real_routed)
    r = await _rpc(client, keys["admin_key"], "tools/call", {"name": "gateway__search_tools", "arguments": {"query": "notes"}})
    assert r.status_code == 400
    assert "Unknown server slug 'gateway'" in r.json()["error"]["message"]


# ---- search: ranking, limits, RBAC ---------------------------------------------------


def test_search_ranking_name_beats_description():
    tools = [
        {"name": "woo__list_orders", "description": "orders of the store"},
        {"name": "notes__create_note", "description": "write an ORDER note"},
    ]
    hits = search_tools(tools, "orders")
    assert hits[0]["name"] == "woo__list_orders"


def test_search_blank_query_lists_catalogue_and_limit_holds():
    tools = [{"name": f"s__t{i}", "description": "x"} for i in range(40)]
    assert len(search_tools(tools, "", 10)) == 10
    assert len(search_tools(tools, "x", 5)) == 5


@pytest.mark.asyncio
async def test_search_respects_role_permissions(harness):
    """The member's denied tool (notes__search_notes) must not be searchable."""
    client, keys, _c = harness
    r = await _rpc(client, keys["member_key"], "tools/call",
                   {"name": "gateway__search_tools", "arguments": {"query": "search notes"}},
                   mode_header="compact")
    assert r.status_code == 200
    payload = json.loads(_result_text(r))
    names = [m["name"] for m in payload["matches"]]
    assert "notes__search_notes" not in names, f"denied tool searchable: {names}"
    # the admin sees it
    r = await _rpc(client, keys["admin_key"], "tools/call",
                   {"name": "gateway__search_tools", "arguments": {"query": "search notes"}},
                   mode_header="compact")
    payload = json.loads(_result_text(r))
    assert "notes__search_notes" in [m["name"] for m in payload["matches"]]


# ---- gateway__call_tool: same routing/permission/audit -------------------------------


@pytest.mark.asyncio
async def test_call_tool_routes_and_audits_real_name(harness):
    client, keys, captured = harness
    r = await _rpc(client, keys["member_key"], "tools/call",
                   {"name": "gateway__call_tool", "arguments": {"name": "notes__list_notes", "arguments": {"q": "hi"}}},
                   mode_header="compact")
    assert r.status_code == 200
    assert "ran notes__list_notes" in _result_text(r)
    real = [c for c in captured if c.get("tool_exposed_name") == "notes__list_notes"]
    assert real, f"audit row does not carry the real tool name: {captured[-1] if captured else None}"
    assert real[-1]["outcome"] == "success"
    # no meta wrapper row: the call_tool shell is invisible in the audit trail
    assert not [c for c in captured if c.get("tool_exposed_name") == "gateway__call_tool"]


@pytest.mark.asyncio
async def test_call_tool_denied_inner_tool_is_unknown_tool(harness):
    """The denied inner tool must get the SAME unknown-tool error a direct call
    gets (no existence leak) and a permission_denied audit row."""
    client, keys, captured = harness
    r = await _rpc(client, keys["member_key"], "tools/call",
                   {"name": "gateway__call_tool", "arguments": {"name": "notes__search_notes", "arguments": {}}},
                   mode_header="compact")
    assert r.status_code == 400
    assert "unknown tool: notes__search_notes" in r.json()["error"]["message"]
    denied = [c for c in captured if c.get("outcome") == "permission_denied"]
    assert denied and denied[-1]["tool_exposed_name"] == "notes__search_notes"


@pytest.mark.asyncio
async def test_call_tool_validates_arguments_shape(harness):
    client, keys, _c = harness
    # missing name
    r = await _rpc(client, keys["member_key"], "tools/call",
                   {"name": "gateway__call_tool", "arguments": {}}, mode_header="compact")
    assert r.status_code == 400
    # meta-in-meta
    r = await _rpc(client, keys["member_key"], "tools/call",
                   {"name": "gateway__call_tool", "arguments": {"name": "gateway__search_tools"}}, mode_header="compact")
    assert r.status_code == 400
    assert "meta tools cannot call meta tools" in r.json()["error"]["message"]
    # non-object arguments
    r = await _rpc(client, keys["member_key"], "tools/call",
                   {"name": "gateway__call_tool", "arguments": {"name": "notes__list_notes", "arguments": "hi"}},
                   mode_header="compact")
    assert r.status_code == 400
    assert "JSON object" in r.json()["error"]["message"]


@pytest.mark.asyncio
async def test_unknown_inner_tool_is_validation_error(harness, monkeypatch):
    client, keys, captured = harness
    from gw_mcp.router import call_tool_routed as real_routed

    monkeypatch.setattr(mcp_route, "call_tool_routed", real_routed)
    r = await _rpc(client, keys["member_key"], "tools/call",
                   {"name": "gateway__call_tool", "arguments": {"name": "nope__nope", "arguments": {}}},
                   mode_header="compact")
    assert r.status_code == 400
    assert "Unknown server slug 'nope'" in r.json()["error"]["message"]
    assert captured[-1]["outcome"] == "validation_error"


# ---- 300 synthetic tools across 10 fake upstreams ------------------------------------


@pytest.mark.asyncio
async def test_full_vs_compact_token_size_300_tools(harness, monkeypatch, capsys):
    """10 fake upstreams x 30 tools: compact tools/list must be ~an order of
    magnitude smaller. Sizes are printed for the BUILD_LOG evidence."""
    client, keys, _c = harness
    synthetic = [
        {
            "name": f"fake{i}__tool_{j}_search_inventory_and_report_metrics",
            "description": f"Synthetic tool {j} of upstream fake{i}: searches inventory and reports metrics for region-{j}",
            "inputSchema": {"type": "object", "properties": {f"arg_{k}": {"type": "string", "description": f"arg {k}"} for k in range(6)}, "required": ["arg_0"]},
        }
        for i in range(10)
        for j in range(30)
    ]
    assert len(synthetic) == 300

    async def fake_fanout(db, servers, timeout_seconds=8):
        return synthetic, []

    monkeypatch.setattr(mcp_route, "fanout_list_tools", fake_fanout)

    r_full = await _rpc(client, keys["admin_key"], "tools/list")
    full_bytes = len(json.dumps(r_full.json()))
    full_tools = len(_tools(r_full))

    r_compact = await _rpc(client, keys["admin_key"], "tools/list", mode_header="compact")
    compact_bytes = len(json.dumps(r_compact.json()))
    compact_tools = len(_tools(r_compact))

    print(f"TOOLS-LIST SIZE: full={full_tools} tools / {full_bytes} bytes; compact={compact_tools} tools / {compact_bytes} bytes; ratio={compact_bytes / full_bytes:.3f}")
    assert full_tools == 300
    assert compact_tools == 2
    assert compact_bytes < full_bytes / 10, f"compact payload {compact_bytes} not < full/10 ({full_bytes // 10})"


# ---- chat agent auto-compact ---------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_auto_compact_above_threshold(monkeypatch):
    """Above compactThreshold the agent sends ONLY the meta tools; a
    gateway__call_tool from the model runs the REAL tool and audits the real
    name."""

    from tests.conftest import chat_user, install_fake_openai, patch_chat_agent

    routed: list[str] = []

    async def route(db, name, args, timeout_seconds=None):
        routed.append(name)
        return {"content": [{"type": "text", "text": f"ran {name}"}], "isError": False}

    class _S:
        openai_api_key = "test-key-not-real"
        openai_base_url = None
        openai_model = "fake-model-a"
        openai_models = ""
        compact_threshold = 2  # tiny so the 3-tool catalogue trips it

        def model_chain(self):
            return ["fake-model-a"]

        def max_models_per_turn(self):
            return 6

    tools = [
        {"name": "notes__list_notes", "description": "list", "inputSchema": {"type": "object", "properties": {}}},
        {"name": "notes__create_note", "description": "create", "inputSchema": {"type": "object", "properties": {}}},
        {"name": "woo__list_products", "description": "products", "inputSchema": {"type": "object", "properties": {}}},
    ]

    seen_tools: list[list[str]] = []
    step = {"n": 0}

    def make_create(captured_tools):
        async def create(*args, **kwargs):
            captured_tools.append([t["function"]["name"] for t in (kwargs.get("tools") or [])])
            step["n"] += 1
            if step["n"] == 1:
                # the model searches first
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content="", tool_calls=[SimpleNamespace(
                        id="c1", function=SimpleNamespace(name="gateway__search_tools", arguments='{"query": "notes"}'))]))])
            if step["n"] == 2:
                # then calls the real tool through the meta shell
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content="", tool_calls=[SimpleNamespace(
                        id="c2", function=SimpleNamespace(name="gateway__call_tool", arguments='{"name": "notes__list_notes", "arguments": {}}'))]))])
            # finally answers
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="here are your notes", tool_calls=[]))])
        return create

    install_fake_openai(monkeypatch, make_create(seen_tools))

    audit_rows: list[dict] = []

    import audit.queue as audit_queue

    async def fake_audit(**kwargs):
        audit_rows.append(kwargs)

    ag = patch_chat_agent(monkeypatch, settings=_S(), tools=tools, route=route, audit=fake_audit)
    monkeypatch.setattr(audit_queue, "log_audit", fake_audit)

    class _DB:
        async def execute(self, stmt):
            class _Res:
                def scalar_one_or_none(self):
                    return "00000000-0000-0000-0000-00000000000a"

            return _Res()

        async def commit(self):
            pass

    events: list[dict] = []
    async for evt in ag.chat_loop(_DB(), chat_user(), [{"role": "user", "content": "search then list notes"}], "req-cm"):
        events.append(evt)

    # only the two meta tools were offered to the LLM
    assert seen_tools and seen_tools[0], "LLM call saw no tools"
    for offered in seen_tools:
        assert set(offered) <= {"gateway__search_tools", "gateway__call_tool"}, offered
    # the REAL tool was routed exactly once, under its real name
    assert routed == ["notes__list_notes"], routed
    # the audit trail carries the real name (and the gateway search op)
    exposed = [r.get("tool_exposed_name") for r in audit_rows]
    assert "gateway__search_tools" in exposed
    assert "notes__list_notes" in exposed
    assert "gateway__call_tool" not in exposed, "the meta shell must be invisible in audit"
    # the chat event shows the REAL tool so the UI stays honest
    tool_events = [e for e in events if e.get("type") == "tool_call"]
    assert any(e["tool"] == "notes__list_notes" and e["outcome"] == "success" for e in tool_events), tool_events
