"""Notes 'upstream error' root-cause fixes (F2 pass, item 1).

The audit trail showed 3 upstream_error rows on the notes server (2 timeouts at
~10s audited as upstream_error, 1 fast protocol failure) — a 3.61% "error rate"
on a healthy in-memory demo server. Reproduced live through the gateway:

1. arguments not a JSON object (model mistake) crashed the MCP SDK client with
   an opaque TaskGroup ExceptionGroup -> 502 "upstream error", audited
   upstream_error.
2. httpx read timeouts surface inside the SDK's TaskGroup ExceptionGroups, so
   they missed the TimeoutError handler and were audited upstream_error/502
   instead of timeout/504.
3. Tool-argument pydantic validation failures arrive as isError tool results
   (a CLEAR tool error for the model) but were audited as upstream_error,
   blaming healthy upstreams for caller mistakes.
4. Those failures also recorded breaker failures: enough bad arguments from an
   LLM could open the circuit of a healthy server.
5. The MCP SDK raises McpError when the upstream rejects the REQUEST at the
   protocol level (-32602): the upstream is alive, so this is a caller error
   (400 validation_error), never an outage.

Upstreams here are fake proxies (monkeypatched proxy_call): no network; the
HTTP-level tests run the REAL app over sqlite, matching the repo's conventions.
"""

from __future__ import annotations

import gw_mcp.router as router
import httpx
import pytest
import routes.mcp as mcp_route
from auth.keys import create_api_key
from auth.rbac import hash_password
from db.models import Base, Server, User
from db.session import get_db
from gw_mcp.breaker import CircuitBreaker
from httpx import ASGITransport
from main import create_app
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from tests.conftest import FakeDB, make_server

ADMIN = {"email": "admin-notes-fix@urumi.local", "password": "notes-fix-pass-123"}

VALIDATION_ISERROR = {
    "content": [
        {
            "type": "text",
            "text": (
                "Error executing tool search_notes: 1 validation error for "
                "search_notesArguments\nquery\n  Field required [type=missing, input_value={}]"
            ),
        }
    ],
    "isError": True,
}


async def _proxy_raising(exc):
    async def proxy(server, tool, arguments, timeout_seconds=None):
        raise exc

    return proxy


@pytest.fixture()
async def mcp_harness():
    """Real app + sqlite with one 'notes' server; audit capture; route mocked per test."""
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
        db.add(admin)
        await db.flush()
        srv = Server(slug="notes", url="http://notes.invalid:8000/mcp", auth_type="none", timeout_ms=5000)
        db.add(srv)
        _row, raw_key = await create_api_key(db, admin.id)
        await db.commit()

    captured: list[dict] = []

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, raw_key, captured
    await engine.dispose()


async def _post_call(client, key, name, arguments):
    return await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
        headers={"Authorization": f"Bearer {key}"},
    )


# ---- router-level contract ----------------------------------------------------------


@pytest.mark.asyncio
async def test_non_object_arguments_raise_validation_error(monkeypatch):
    """'arguments': 'hello' used to crash the SDK client (TaskGroup ExceptionGroup)
    and surfaced as RuntimeError -> 502 upstream error. It is a caller mistake:
    call_tool_routed must reject it as ValueError BEFORE touching the network."""
    srv = make_server(slug="notes")
    breaker = CircuitBreaker()
    monkeypatch.setattr(router, "breaker", breaker)

    async def must_not_be_called(server, tool, arguments, timeout_seconds=None):
        raise AssertionError("non-object arguments must be rejected before proxy_call")

    monkeypatch.setattr(router, "proxy_call", must_not_be_called)
    for bad in ["hello", [1, 2], 42, True]:
        with pytest.raises(ValueError, match="expected a JSON object"):
            await router.call_tool_routed(FakeDB([srv]), "notes__list_notes", bad)
    assert breaker.state_for(srv.id) == "closed"
    assert srv.status == "Unknown", "a rejected request must not mark the server Unreachable"


@pytest.mark.asyncio
async def test_mcp_error_from_upstream_is_validation_error_not_upstream_error(monkeypatch):
    """The upstream ANSWERED with a JSON-RPC error (e.g. -32602): transport alive,
    request rejected. Must raise ValueError (validation_error), not RuntimeError."""
    srv = make_server(slug="notes")
    breaker = CircuitBreaker()
    monkeypatch.setattr(router, "breaker", breaker)

    async def mcp_error_proxy(server, tool, arguments, timeout_seconds=None):
        raise McpError(ErrorData(code=-32602, message="Invalid request params"))

    monkeypatch.setattr(router, "proxy_call", mcp_error_proxy)
    with pytest.raises(ValueError, match="upstream rejected the request"):
        await router.call_tool_routed(FakeDB([srv]), "notes__search_notes", {"query": "x"})
    assert breaker.state_for(srv.id) == "closed", "a responsive upstream must not trip the breaker"
    assert srv.status == "Unknown", "a protocol rejection must not mark the server Unreachable"


@pytest.mark.asyncio
async def test_taskgroup_httpx_timeout_is_timeout_not_upstream_error(monkeypatch):
    """The two 10s notes failures were httpx read timeouts wrapped in the SDK's
    TaskGroup ExceptionGroup: they missed the TimeoutError handler and were
    audited upstream_error/502. They must raise TimeoutError (outcome timeout)."""
    srv = make_server(slug="notes", timeout_ms=5000)
    breaker = CircuitBreaker()
    monkeypatch.setattr(router, "breaker", breaker)
    proxy = await _proxy_raising(ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [httpx.ReadTimeout("read timed out")]))
    monkeypatch.setattr(router, "proxy_call", proxy)
    with pytest.raises(TimeoutError, match="timed out"):
        await router.call_tool_routed(FakeDB([srv]), "notes__list_notes", {})
    assert srv.last_error == "timeout"


@pytest.mark.asyncio
async def test_bare_httpx_timeout_is_timeout_not_upstream_error(monkeypatch):
    """Even a DIRECT httpx.TimeoutException (not grouped) is not a Python
    TimeoutError, so it must be re-classified from the cause chain."""
    srv = make_server(slug="notes", timeout_ms=5000)
    breaker = CircuitBreaker()
    monkeypatch.setattr(router, "breaker", breaker)

    async def timeout_proxy(server, tool, arguments, timeout_seconds=None):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(router, "proxy_call", timeout_proxy)
    with pytest.raises(TimeoutError, match="timed out"):
        await router.call_tool_routed(FakeDB([srv]), "notes__list_notes", {})


@pytest.mark.asyncio
async def test_connection_refused_still_is_upstream_error(monkeypatch):
    """A genuinely dead upstream must still be upstream_error (RuntimeError)."""
    srv = make_server(slug="notes")
    breaker = CircuitBreaker()
    monkeypatch.setattr(router, "breaker", breaker)

    async def dead_proxy(server, tool, arguments, timeout_seconds=None):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(router, "proxy_call", dead_proxy)
    with pytest.raises(RuntimeError, match="Upstream notes error"):
        await router.call_tool_routed(FakeDB([srv]), "notes__list_notes", {})
    assert srv.last_error == "connection refused"


# ---- /mcp HTTP-level classification through the REAL app ----------------------------


@pytest.mark.asyncio
async def test_string_arguments_returns_400_validation_error_not_502(mcp_harness, monkeypatch):
    """THE reproduced notes failure: 'arguments': 'hello' (a model mistake) used to
    return 502 'upstream error: unhandled errors in a TaskGroup' and audit
    upstream_error. It must be a 400 -32602 validation error."""
    client, raw_key, captured = mcp_harness

    async def fake_log_audit(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(mcp_route, "log_audit", fake_log_audit)
    r = await _post_call(client, raw_key, "notes__list_notes", "hello")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == -32602
    assert "expected a JSON object" in r.json()["error"]["message"]
    assert captured and captured[-1]["outcome"] == "validation_error"


@pytest.mark.asyncio
async def test_tool_validation_iserror_audits_validation_error_but_stays_tool_error(mcp_harness, monkeypatch):
    """FastMCP argument-validation failures arrive as isError results. The MODEL
    still gets a clear tool error (response unchanged), but the audit must say
    validation_error — not blame the upstream (this inflated notes to 3.6%)."""
    client, raw_key, captured = mcp_harness

    async def fake_log_audit(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(mcp_route, "log_audit", fake_log_audit)

    async def validation_route(*args, **kwargs):
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Error executing tool search_notes: 1 validation error for "
                        "search_notesArguments\nquery\n  Field required [type=missing]"
                    ),
                }
            ],
            "isError": True,
        }

    monkeypatch.setattr(mcp_route, "call_tool_routed", validation_route)
    r = await _post_call(client, raw_key, "notes__search_notes", {})
    assert r.status_code == 200 and r.json()["result"]["isError"] is True
    assert captured[-1]["outcome"] == "validation_error"
    assert captured[-1]["error_code"] == "validation_error"

    # a REAL tool failure (no pydantic signature) must still audit as upstream_error
    async def woo_auth_route(*args, **kwargs):
        return {"content": [{"type": "text", "text": "WOO_AUTH_FAILED: bad consumer key"}], "isError": True}

    monkeypatch.setattr(mcp_route, "call_tool_routed", woo_auth_route)
    captured.clear()
    await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "woo__get_order", "arguments": {}}},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert captured[-1]["outcome"] == "upstream_error"
    assert captured[-1]["error_code"] == "WOO_AUTH_FAILED"

