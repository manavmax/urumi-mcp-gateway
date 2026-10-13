"""tools/call results must be valid MCP wire content for STRICT clients (MCP Inspector).

Regression for "Tool Call Failed: Invalid result for tools/call: content.0: Invalid input".

The gateway re-serialised upstream CallToolResults with `TextContent.model_dump()`,
emitting `"annotations": null` / `"meta": null` on every block (and dropping
structuredContent). The MCP TypeScript SDK — what MCP Inspector and many real clients
run — types `annotations`/`_meta` as *optional* (undefined only, never null) inside a
plain z.union, so ONE null field fails the whole content-block union and the client
reports `content.0: Invalid input`. The Python SDK 1.12.x client tolerates the shape
(models allow extra keys and field-name population), which is exactly why earlier
verify runs looked green while the Inspector failed.

These tests drive the REAL FastAPI app + REAL sqlite DB + the REAL MCP SDK client
(streamablehttp_client + ClientSession.call_tool) against a REAL in-process FastMCP
upstream, then re-validate the raw JSON-RPC response bytes with a strict wire check
that mirrors what the TypeScript SDK enforces: known block types only, whitelisted
fields, no null values anywhere (spec-optional means absent, never null).
"""

from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ResourceLink, TextContent, TextResourceContents
from sqlalchemy import CheckConstraint
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from auth.keys import create_api_key
from auth.rbac import hash_password
from db.models import Base, Server, User
from db.session import get_db
from gw_mcp.router import _assert_wire_content, _rebuild_content
from main import create_app

MEMBER = {"email": "wire-member@urumi.local", "password": "member-wire-pass-123"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class UvicornHolder:
    """uvicorn server on a real local socket, owned by a daemon thread."""

    def __init__(self, app):
        self.port = _free_port()
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("uvicorn did not start")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)


# strict wire check mirrors the TypeScript SDK's zod validation of CallToolResult:
# content blocks must be known types with only spec fields and NEVER a null value
# (spec-optional means ABSENT, never null); structuredContent must be an object
# when present ("expected record, received null" is a hard client error).
_BLOCK_KEYS = {
    "text": {"type", "text"},
    "image": {"type", "data", "mimeType"},
    "audio": {"type", "data", "mimeType"},
    "resource_link": {"type", "uri", "name", "description", "mimeType"},
    "resource": {"type", "resource"},
}


def _assert_no_nulls(value, path: str) -> None:
    if value is None:
        raise AssertionError(f"{path} is null (strict clients reject explicit null)")
    if isinstance(value, dict):
        for k, v in value.items():
            _assert_no_nulls(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _assert_no_nulls(v, f"{path}[{i}]")


def strict_wire_check(result: dict, label: str) -> None:
    assert isinstance(result, dict), f"{label}: result is not an object"
    content = result.get("content")
    assert isinstance(content, list) and content, f"{label}: result.content missing"
    for i, b in enumerate(content):
        assert isinstance(b, dict), f"{label}: content[{i}] not an object"
        btype = b.get("type")
        assert btype in _BLOCK_KEYS, f"{label}: content[{i}] unknown type {btype!r}"
        extra = set(b) - _BLOCK_KEYS[btype]
        assert not extra, f"{label}: content[{i}] unknown fields {sorted(extra)}"
        for k, v in b.items():
            assert v is not None, f"{label}: content[{i}].{k} is null (strict clients reject)"
        if btype == "text":
            assert isinstance(b["text"], str) and b["text"], f"{label}: empty text"
        if btype == "resource":
            assert isinstance(b["resource"], dict), f"{label}: resource must be object"
    if "structuredContent" in result:
        assert isinstance(result["structuredContent"], dict), (
            f"{label}: structuredContent must be an object when present, "
            f"got {result['structuredContent']!r}"
        )
    _assert_no_nulls(result, label)


# ---------------- unit-level: the exact poison shapes ----------------


def test_wire_check_rejects_the_inspector_failure_shape():
    """The old TextContent.model_dump() output must FAIL the strict check — this was the bug."""
    poison = [{"type": "text", "text": "hi", "annotations": None, "meta": None}]
    with pytest.raises(ValueError):
        _assert_wire_content(poison)


def test_wire_check_rejects_null_structured_content():
    result = {"content": [{"type": "text", "text": "hi"}], "structuredContent": None, "isError": False}
    with pytest.raises(AssertionError):
        strict_wire_check(result, "null structuredContent")


def test_rebuild_strips_nulls_and_unknown_fields():
    blocks = _rebuild_content([TextContent(type="text", text="hi", annotations=None, meta={"a": "b"})])
    assert blocks == [{"type": "text", "text": "hi"}]
    _assert_wire_content(blocks)


def test_rebuild_covers_all_sdk_block_types():
    blocks = _rebuild_content(
        [
            TextContent(type="text", text="t"),
            ResourceLink(type="resource_link", uri="file:///x.txt", name="x"),
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(uri="file:///y.txt", mimeType="text/plain", text="body"),
            ),
            "totally-unknown-block",  # no type/dict shape -> degrades to text, never invalid
        ]
    )
    assert blocks[0] == {"type": "text", "text": "t"}
    assert blocks[1] == {"type": "resource_link", "uri": "file:///x.txt", "name": "x"}
    assert blocks[2]["type"] == "resource" and blocks[2]["resource"]["text"] == "body"
    assert blocks[3]["type"] == "text"
    _assert_wire_content(blocks)


# ---------------- real SDK client end-to-end ----------------


@pytest.fixture()
async def upstream_url():
    """A REAL MCP upstream (FastMCP) over HTTP on 127.0.0.1 — what the gateway proxies to."""
    upstream = FastMCP("up")

    @upstream.tool()
    def echo(msg: str) -> str:
        """echo back"""
        return f"echo:{msg}"

    @upstream.tool()
    def fail() -> str:
        """always raises"""
        raise RuntimeError("UPSTREAM_BOOM")

    holder = UvicornHolder(upstream.streamable_http_app())
    yield f"http://127.0.0.1:{holder.port}/mcp"
    holder.stop()


@pytest.fixture()
async def running_gateway(upstream_url):
    """REAL FastAPI app + REAL sqlite DB + uvicorn on a local port (real sockets, real SDK client)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    for table in Base.metadata.tables.values():
        # the Postgres-only regex CHECK cannot compile on sqlite
        table.constraints = {c for c in table.constraints if not isinstance(c, CheckConstraint)}
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    # Skip only the app lifespan (alembic + seed against the REAL postgres default):
    # under uvicorn it would run for real. Routes, auth middleware, RBAC, the DB
    # override and every handler below stay exactly as production.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app.router.lifespan_context = _noop_lifespan

    async with SessionLocal() as db:
        member = User(email=MEMBER["email"], password_hash=await hash_password(MEMBER["password"]), role="member", is_active=True)
        db.add(member)
        await db.flush()
        srv = Server(slug="up", url=upstream_url, auth_type="none", timeout_ms=10000)
        db.add(srv)
        _row, member_key = await create_api_key(db, member.id)
        await db.commit()

    # proxy_call and the tools/list fan-out SSRF-guard loopback hosts; SSRF has its
    # own tests — here we are testing the wire schema, so neutralise only that DNS gate.
    import gw_mcp.router as router_module
    import registry.validator as validator_module

    async def _allow(host):
        return None

    router_module.resolve_and_validate = _allow
    validator_module.resolve_and_validate = _allow

    holder = UvicornHolder(app)
    yield f"http://127.0.0.1:{holder.port}/mcp", member_key
    holder.stop()
    await engine.dispose()

def _captured_tool_result(captured: list[dict], tool_hint: str = "") -> dict:
    """Latest tools/call response envelope from the capture list."""
    for body in reversed(captured):
        res = body.get("result")
        if isinstance(res, dict) and isinstance(res.get("content"), list):
            return res
    raise AssertionError(f"no tools/call result captured (tool={tool_hint})")


async def test_tools_call_results_are_wire_valid_through_real_sdk_client(upstream_url, running_gateway):
    gw_url, member_key = running_gateway
    captured: list[dict] = []

    def outer_factory(**kwargs):
        async def _capture(response: httpx.Response):
            body = await response.aread()
            if response.request.url.path == "/mcp" and response.status_code == 200:
                try:
                    captured.append(json.loads(body))
                except Exception:
                    pass

        kwargs.setdefault("timeout", 30)
        return httpx.AsyncClient(**{**kwargs, "event_hooks": {"response": [_capture]}})

    async with streamablehttp_client(gw_url, headers={"Authorization": f"Bearer {member_key}"}, httpx_client_factory=outer_factory) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listing = await session.list_tools()
            names = [t.name for t in listing.tools]
            assert "up__echo" in names, f"tools/list via gateway: {names}"

            # success result: the real SDK client must parse it, and the raw JSON-RPC
            # bytes must survive the strict (TS-SDK-style) wire check.
            res = await session.call_tool("up__echo", {"msg": "hello"})
            assert res.isError is False
            texts = [b.text for b in res.content if b.type == "text"]
            assert any("echo:hello" in t for t in texts), texts
            raw = _captured_tool_result(captured, "up__echo")
            strict_wire_check(raw, "up__echo success")
            # EXACT minimal wire shape: no annotations/meta keys, no degraded
            # JSON-dump fallback block (a regression to model_dump() must fail here).
            assert raw["content"][0] == {"type": "text", "text": "echo:hello"}

            # upstream tool failure (isError=true) is ALSO a CallToolResult: same rules.
            res2 = await session.call_tool("up__fail", {})
            assert res2.isError is True
            err_text = " ".join(b.text for b in res2.content if b.type == "text")
            assert "UPSTREAM_BOOM" in err_text, err_text
            raw_err = captured[-1]["result"]
            strict_wire_check(raw_err, "up__fail isError")
            # error results must carry the readable tool error, not a degraded JSON dump
            assert not raw_err["content"][0]["text"].lstrip().startswith("{"), raw_err
