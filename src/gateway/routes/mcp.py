"""Gateway MCP endpoint: POST/GET /mcp — Streamable HTTP JSON-RPC.

Stateless gateway: no Mcp-Session-Id. Handles:
- initialize
- notifications/initialized
- tools/list (fan-out with isolation + RBAC)
- tools/call (prefix routing + RBAC + audit + circuit breaker)
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from audit.queue import log_audit
from db.models import Server
from db.session import get_db
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from gw_mcp.aggregator import fanout_list_tools, list_cached_tools, split_exposed
from gw_mcp.compact import (
    CALL_TOOL_NAME,
    COMPACT_TOOLS,
    SEARCH_TOOL_NAME,
    compact_mode_selected,
    is_meta_tool,
    search_result_content,
    search_tools,
)
from gw_mcp.permissions import assert_call_allowed
from gw_mcp.router import call_tool_routed
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("gateway.mcp")

router = APIRouter()

PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "urumi-gateway", "version": "1.0.0"}


def _record_metrics(slug: str, name: str, outcome: str, duration_ms: int) -> None:
    """Mirror one audited tool call into the Prometheus counters/histograms
    (Phase 1). Fails safe inside gw_mcp.metrics."""
    from gw_mcp.metrics import observe_tool_call

    observe_tool_call(slug, name, outcome, duration_ms)

PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "urumi-gateway", "version": "1.0.0"}


def _jsonrpc_error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _jsonrpc_result(id_: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _oauth_401_headers() -> dict:
    """RFC 9728 pointer for unauthenticated MCP clients (Phase 7, ADR-063).
    Only when OAuth is enabled; plain API-key 401s keep the bare shape."""
    from config import get_settings

    if not get_settings().oauth_enabled:
        return {}
    from oauth.core import www_authenticate_header

    return {"WWW-Authenticate": www_authenticate_header()}


@router.get("/mcp")
async def mcp_get(request: Request):
    # GET /mcp with SSE is optional; we support JSON-RPC via POST only.
    # Return 405 for SSE clients that expect stream; Inspector uses POST.
    return JSONResponse(
        {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Use POST /mcp with JSON-RPC. GET SSE not required for stateless gateway."}},
        status_code=405,
    )


@router.post("/mcp")
async def mcp_post(request: Request, db: AsyncSession = Depends(get_db)):
    # Auth: must have valid API key (sets request.state.current_user)
    # We call dependency manually to get proper audit attribution
    from auth.keys import verify_api_key

    auth = request.headers.get("authorization", "") or request.headers.get("Authorization", "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.headers.get("x-api-key", "").strip()

    # body size guard
    body_bytes = await request.body()
    if len(body_bytes) > 1_000_000:
        return JSONResponse(_jsonrpc_error(None, -32700, "request too large"), status_code=413)

    try:
        payload = json.loads(body_bytes) if body_bytes else {}
    except json.JSONDecodeError:
        return JSONResponse(_jsonrpc_error(None, -32700, "parse error"), status_code=400)

    # Require auth for all methods except we still want 401 shape
    from auth.rate_limit import effective_key_limit

    user = None
    api_key_id = None
    key_limit = None  # None = the default per-key limit (OAuth bearer calls)
    if not token:
        # Phase 7 (ADR-063): unauthenticated 401s carry WWW-Authenticate
        # pointing MCP clients at the protected-resource metadata (RFC 9728)
        return JSONResponse(
            _jsonrpc_error(payload.get("id"), -32000, "missing bearer token"),
            status_code=401,
            headers=_oauth_401_headers(),
        )
    res = await verify_api_key(db, token)
    if res:
        user, key_row = res
        api_key_id = key_row.id
        key_limit = effective_key_limit(key_row)
    else:
        # not an API key: when OAuth is on, try an OAuth access token (uat_...)
        from config import get_settings as _gs

        if token.startswith("uat_") and _gs().oauth_enabled:
            from oauth.core import OauthError, authenticate_bearer

            try:
                res2 = await authenticate_bearer(db, token)
            except OauthError:
                res2 = None
            if res2:
                user, _tok = res2
            else:
                return JSONResponse(
                    _jsonrpc_error(payload.get("id"), -32000, "invalid or expired access token"),
                    status_code=401,
                    headers=_oauth_401_headers(),
                )
        else:
            return JSONResponse(
                _jsonrpc_error(payload.get("id"), -32000, "invalid or revoked key"),
                status_code=401,
                headers=_oauth_401_headers(),
            )
    request.state.current_user = user
    request.state.api_key_id = api_key_id

    # Rate limits (ADR-057): per KEY (override or default) and per USER, counters
    # in Postgres so they hold across replicas. Chat tool calls count against
    # the same user budget inside the chat agent.
    from auth.rate_limit import consume_and_check

    allowed, limit_scope, retry_after = await consume_and_check(
        user_id=user.id,
        api_key_id=api_key_id,
        # OAuth bearer calls carry no API key: key_limit stays None (the
        # default per-key limit applies) and the per-USER counter is what
        # actually bounds them (ADR-057 + ADR-063)
        key_limit=key_limit,
    )
    if not allowed:
        from gw_mcp.metrics import inc_rate_limited

        inc_rate_limited(limit_scope)
        request_id = uuid.uuid4()
        client_ip = request.client.host if request.client else None
        await log_audit(
            user_id=user.id,
            api_key_id=api_key_id,
            server_id=None,
            server_slug="unknown",
            tool_exposed_name=payload.get("params", {}).get("name", "unknown") if isinstance(payload.get("params"), dict) else "unknown",
            tool_upstream_name="unknown",
            request_id=request_id,
            duration_ms=0,
            outcome="rate_limited",
            error_code=f"rate_limited_{limit_scope}",
            client_ip=client_ip,
        )
        return JSONResponse(
            _jsonrpc_error(payload.get("id"), -32000, f"rate limit exceeded ({limit_scope} limit), retry after {retry_after} seconds"),
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    method = payload.get("method")
    msg_id = payload.get("id")
    client_ip = request.client.host if request.client else None
    request_id = uuid.uuid4()

    # Phase 3 (ADR-058): compact mode is selected by the client (header or query
    # param) and changes ONLY tools/list (two meta tools) and tools/call of the
    # meta tools. Default mode is byte-for-byte unchanged.

    compact = compact_mode_selected(request.headers.get("x-gateway-mode"), request.query_params.get("mode"))

    # notifications/initialized has no id and expects 202
    if method == "notifications/initialized":
        return Response(status_code=202)

    if method == "initialize":
        # Echo protocol version, return capabilities. The version the CLIENT asked
        # for is deliberately not echoed: this gateway answers with its own.
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": True}},
            "serverInfo": SERVER_INFO,
            "instructions": "Use tools via gateway; tools are prefixed slug__tool. All calls are audited.",
        }
        return JSONResponse(_jsonrpc_result(msg_id, result))

    if method == "tools/list":
        # RBAC: for now all enabled servers visible to all users; per-tool RBAC can filter here
        # Fetch enabled servers
        servers_res = await db.execute(select(Server).where(Server.enabled.is_(True)))
        servers = list(servers_res.scalars().all())
        if not servers:
            return JSONResponse(_jsonrpc_result(msg_id, {"tools": []}))
        # Phase 3 (ADR-058): compact mode serves two meta tools instead of the
        # full catalogue - clients then search + call by name. The list still
        # respects the caller's role permissions when searching.
        if compact:
            return JSONResponse(_jsonrpc_result(msg_id, {"tools": [dict(t) for t in COMPACT_TOOLS]}))
        # Try fan-out with timeout 8s; on failure fall back to cached tools
        try:
            tools, warnings = await fanout_list_tools(db, servers, timeout_seconds=8)
        except Exception as exc:
            logger.warning("fanout failed, falling back to cache: %s", exc)
            tools = await list_cached_tools(db, [s.id for s in servers])
            warnings = [{"error": str(exc)[:500]}]
        # RBAC: filter per-role tool deny rules (members); admins see everything
        tools = await _filter_tools_by_rbac(db, user, tools)
        result = {"tools": tools}
        if warnings:
            result["_meta"] = {"warnings": warnings}
        return JSONResponse(_jsonrpc_result(msg_id, result))

    if method == "tools/call":
        params = payload.get("params", {}) or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            return JSONResponse(_jsonrpc_error(msg_id, -32602, "missing tool name"), status_code=400)

        # ---- Phase 3 (ADR-058): the compact-mode meta tools ------------------
        # Both are handled here so the DEFAULT tools/call path stays untouched;
        # in default mode the meta names are NOT special (they fall through to
        # the unknown-slug validation error, exactly as before).
        if compact and is_meta_tool(name):
            if name == SEARCH_TOOL_NAME:
                # Search the RBAC-filtered catalogue (the same filter the full
                # tools/list applies). The search itself is audited as a
                # gateway operation; no upstream is contacted.
                query = str(arguments.get("query") or "")
                try:
                    limit = int(arguments.get("limit") or 20)
                except (TypeError, ValueError):
                    limit = 20
                servers_res = await db.execute(select(Server).where(Server.enabled.is_(True)))
                servers = list(servers_res.scalars().all())
                tools = await list_cached_tools(db, [s.id for s in servers])
                tools = await _filter_tools_by_rbac(db, user, tools)
                matches = search_tools(tools, query, limit)
                result = search_result_content(matches, query)
                await log_audit(
                    user_id=user.id,
                    api_key_id=api_key_id,
                    server_id=None,
                    server_slug="gateway",
                    tool_exposed_name=SEARCH_TOOL_NAME,
                    tool_upstream_name=SEARCH_TOOL_NAME,
                    request_id=request_id,
                    duration_ms=0,
                    outcome="success",
                    error_code=None,
                    client_ip=client_ip,
                )
                _record_metrics("gateway", SEARCH_TOOL_NAME, "success", 0)
                return JSONResponse(_jsonrpc_result(msg_id, result))
            if name == CALL_TOOL_NAME:
                # Unwrap the real tool call; then it flows through the SAME
                # permission / routing / timeout / audit code as a direct call,
                # and the audit row carries the REAL tool name.
                inner_name = arguments.get("name")
                inner_args = arguments.get("arguments")
                if not isinstance(inner_name, str) or not inner_name:
                    return JSONResponse(
                        _jsonrpc_error(msg_id, -32602, f"{CALL_TOOL_NAME} needs a tool name"), status_code=400
                    )
                if is_meta_tool(inner_name):
                    return JSONResponse(
                        _jsonrpc_error(msg_id, -32602, "meta tools cannot call meta tools"), status_code=400
                    )
                if inner_args is None:
                    inner_args = {}
                if not isinstance(inner_args, dict):
                    return JSONResponse(
                        _jsonrpc_error(msg_id, -32602, f"arguments for {inner_name} must be a JSON object"), status_code=400
                    )
                name = inner_name
                arguments = inner_args
        # ---------------------------------------------------------------------

        # RBAC check: deny rules for the caller's role (members). Admins always allowed.
        # This is the ONE enforcement point for /mcp calls; the chat agent uses the same
        # core (gw_mcp.permissions.assert_call_allowed). A denied call is rejected BEFORE
        # routing upstream, is audited as permission_denied, and returns the standard
        # unknown-tool error so the caller learns nothing about the tool's existence.
        try:
            await assert_call_allowed(db, user, name)
        except PermissionError:
            await log_audit(
                user_id=user.id,
                api_key_id=api_key_id,
                server_id=None,
                server_slug=name.split("__")[0] if "__" in name else "unknown",
                tool_exposed_name=name,
                tool_upstream_name=name.split("__", 1)[1] if "__" in name else name,
                request_id=request_id,
                duration_ms=0,
                outcome="permission_denied",
                error_code="permission_denied",
                client_ip=client_ip,
            )
            _record_metrics(name.split("__")[0] if "__" in name else "unknown", name, "permission_denied", 0)
            # identical to the unknown-tool error (no existence leak)
            return JSONResponse(_jsonrpc_error(msg_id, -32602, f"unknown tool: {name}"), status_code=400)

        # split to get slug for audit
        try:
            slug, upstream = split_exposed(name)
        except ValueError as exc:
            return JSONResponse(_jsonrpc_error(msg_id, -32602, str(exc)), status_code=400)

        # Lookup server for audit meta
        srv_res = await db.execute(select(Server).where(Server.slug == slug))
        srv = srv_res.scalars().first()

        start = time.monotonic()
        try:
            result = await call_tool_routed(db, name, arguments)
            duration_ms = int((time.monotonic() - start) * 1000)
            # An upstream tool that ran but failed comes back isError=true inside a
            # 200 envelope: MCP maps every tool exception to CallToolResult. Auditing
            # that as "success" would hide tool-level failures (e.g. WOO_AUTH_FAILED,
            # schema rejections) from the audit trail, so classify it here.
            upstream_error_code = _upstream_error_code(result)
            tool_validation = _is_tool_validation_error(result)
            outcome = (
                "validation_error"
                if tool_validation
                else ("success" if upstream_error_code is None else "upstream_error")
            )
            error_code = "validation_error" if tool_validation else upstream_error_code
            await log_audit(
                user_id=user.id,
                api_key_id=api_key_id,
                server_id=srv.id if srv else None,
                server_slug=slug,
                tool_exposed_name=name,
                tool_upstream_name=upstream,
                request_id=request_id,
                duration_ms=duration_ms,
                outcome=outcome,
                error_code=error_code,
                client_ip=client_ip,
            )
            _record_metrics(slug, name, outcome, duration_ms)
            # MCP spec: tools/call success is result.content + isError
            return JSONResponse(_jsonrpc_result(msg_id, result))
        except TimeoutError as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            await log_audit(
                user_id=user.id,
                api_key_id=api_key_id,
                server_id=srv.id if srv else None,
                server_slug=slug,
                tool_exposed_name=name,
                tool_upstream_name=upstream,
                request_id=request_id,
                duration_ms=duration_ms,
                outcome="timeout",
                error_code="timeout",
                client_ip=client_ip,
            )
            _record_metrics(slug, name, "timeout", duration_ms)
            return JSONResponse(_jsonrpc_error(msg_id, -32000, str(exc)), status_code=504)
        except RuntimeError as exc:
            msg = str(exc)
            is_circuit = "circuit open" in msg.lower()
            outcome = "circuit_open" if is_circuit else "upstream_error"
            status = 503 if is_circuit else 502
            duration_ms = int((time.monotonic() - start) * 1000)
            # the SAFE classified reason (gw_mcp.categorize) rides on the router's
            # UpstreamCallError; the raw exception text is never stored
            category = getattr(exc, "category", None)
            await log_audit(
                user_id=user.id,
                api_key_id=api_key_id,
                server_id=srv.id if srv else None,
                server_slug=slug,
                tool_exposed_name=name,
                tool_upstream_name=upstream,
                request_id=request_id,
                duration_ms=duration_ms,
                outcome=outcome,
                error_code=category or outcome,
                client_ip=client_ip,
            )
            _record_metrics(slug, name, outcome, duration_ms)
            return JSONResponse(_jsonrpc_error(msg_id, -32000, msg), status_code=status)
        except ValueError as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            await log_audit(
                user_id=user.id,
                api_key_id=api_key_id,
                server_id=srv.id if srv else None,
                server_slug=slug,
                tool_exposed_name=name,
                tool_upstream_name=upstream,
                request_id=request_id,
                duration_ms=duration_ms,
                outcome="validation_error",
                error_code="validation_error",
                client_ip=client_ip,
            )
            _record_metrics(slug, name, "validation_error", duration_ms)
            return JSONResponse(_jsonrpc_error(msg_id, -32602, str(exc)), status_code=400)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            await log_audit(
                user_id=user.id,
                api_key_id=api_key_id,
                server_id=srv.id if srv else None,
                server_slug=slug,
                tool_exposed_name=name,
                tool_upstream_name=upstream,
                request_id=request_id,
                duration_ms=duration_ms,
                outcome="upstream_error",
                error_code="upstream_error",
                client_ip=client_ip,
            )
            _record_metrics(slug, name, "upstream_error", duration_ms)
            return JSONResponse(_jsonrpc_error(msg_id, -32000, f"upstream error: {exc}"), status_code=502)

    if method == "ping":
        return JSONResponse(_jsonrpc_result(msg_id, {}))

    return JSONResponse(_jsonrpc_error(msg_id, -32601, f"unknown method {method}"), status_code=400)


# ---- RBAC: per-role tool deny rules (the ONE enforcement core, ADR-033) ----

def _upstream_error_code(result: dict | None) -> str | None:
    """Return a stable error code when a proxied tool ran but failed.

    Upstream tool exceptions arrive as a 200 JSON-RPC envelope with
    `isError: true` and a text payload (MCP maps every tool exception to
    CallToolResult). The payload usually starts with a stable machine-readable
    code (`WOO_AUTH_FAILED: ...`, `Error executing tool ...`); extract it so the
    audit row says more than "upstream_error". Returns None for plain success.
    """

    if not isinstance(result, dict) or not result.get("isError"):
        return None
    text = ""
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text") or ""
            break
    match = re.match(r"([A-Z][A-Z0-9_]{2,})\s*:", text)
    if match:
        return match.group(1)
    return "upstream_error"


def _is_tool_validation_error(result: dict | None) -> bool:
    """True when an upstream tool failed on ARGUMENT validation (F2 pass).

    FastMCP maps tool-argument pydantic failures to isError results whose text
    reads "Error executing tool X: 1 validation error for XArguments ...". The
    caller (the model) caused that failure with bad arguments and receives a
    clear isError tool result either way — but auditing it as upstream_error
    blamed healthy upstreams for caller mistakes and inflated their error rate
    (the notes server showed 3.6% 'upstream errors' this way). The pydantic
    signature ("<n> validation error(s) for") is specific enough that ordinary
    tool payloads cannot match it.
    """

    if not isinstance(result, dict) or not result.get("isError"):
        return False
    for block in result.get("content") or []:
        if (
            isinstance(block, dict)
            and block.get("type") == "text"
            and re.search(r"\d+ validation errors? for", block.get("text") or "")
        ):
            return True
    return False


async def _filter_tools_by_rbac(db, user, tools: list[dict]) -> list[dict]:
    """tools/list: hide per-role denied tools. Admins always see all."""
    from gw_mcp.permissions import filter_tools_for_user

    return await filter_tools_for_user(db, user, tools)
