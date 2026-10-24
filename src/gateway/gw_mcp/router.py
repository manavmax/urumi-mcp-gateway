"""tools/call routing via prefix slug__tool (docs/02 §3.2, 04 §6.2)."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from config import get_settings
from db.models import LEGACY_TIMEOUT_MS, Server
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError
from registry.crypto import decrypt
from registry.validator import resolve_and_validate
from sqlalchemy.ext.asyncio import AsyncSession

from gw_mcp.aggregator import split_exposed
from gw_mcp.breaker import breaker
from gw_mcp.categorize import CATEGORY_TIMEOUT, classify
from gw_mcp.health_state import record_failure, record_success

logger = logging.getLogger("gateway.router")

ALLOWED_OUTCOMES = {"success", "upstream_error", "permission_denied", "timeout", "circuit_open", "validation_error"}


class UpstreamCallError(RuntimeError):
    """An upstream tool call failed; carries the SAFE classified reason.

    `category` is a stable token from gw_mcp.categorize (connection_refused,
    timeout, dns_failure, tls_error, http_error:<code>, protocol_error,
    invalid_response, auth_rejected, other) - the only thing about the failure
    that is ever stored (audit error_code) or displayed. The exception MESSAGE
    may contain exception text, so it must never be stored or logged verbatim.
    """

    def __init__(self, message: str, category: str):
        super().__init__(message)
        self.category = category


# ---- MCP wire-shape safety net -----------------------------------------------------
#
# The gateway re-serialises upstream CallToolResults into plain JSON dicts. A
# naive `TextContent.model_dump()` emits schema-invalid wire shapes like
# `"annotations": null` and `"meta": null`: the MCP TypeScript SDK (what MCP
# Inspector and many real clients run) types `annotations`/`_meta` as *optional*
# (undefined only, never null) inside a non-discriminated z.union, so ONE null
# field fails the whole content block union and the client reports
# "Invalid result for tools/call: content.0: Invalid input". The Python SDK
# 1.12.x accepts its own output (models allow extra keys), which is exactly why
# earlier verify runs looked green. Rule: emit only the fields the spec defines,
# never a None value, and strictly re-validate before returning anything.

_TEXT_KEYS = {"type", "text"}
_DATA_KEYS = {"type", "data", "mimeType"}
_RESOURCE_LINK_KEYS = {"type", "uri", "name", "description", "mimeType"}
_EMBEDDED_KEYS = {"type", "resource"}


def _no_nulls(obj) -> bool:
    """True when the JSON value contains no None anywhere (None ≠ a spec-optional field)."""
    if obj is None:
        return False
    if isinstance(obj, dict):
        return all(_no_nulls(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return all(_no_nulls(v) for v in obj)
    return True


def _rebuild_content_block(block) -> dict | None:
    """Rebuild one upstream content block as a minimal, spec-valid content dict.

    Field-whitelisted per block type: no None-valued fields, no unknown fields.
    Unrecognised block types degrade to a text block (the JSON payload is kept in
    the text) so a client never sees a block it cannot parse.
    """
    # tolerate already-serialised upstream dicts as well as SDK models
    btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)

    def _get(key, default=None):
        if isinstance(block, dict):
            return block.get(key, default)
        return getattr(block, key, None)

    if btype == "text":
        text = _get("text")
        if isinstance(text, str):
            return {"type": "text", "text": text}
    elif btype in ("image", "audio"):
        data, mime = _get("data"), _get("mimeType")
        if isinstance(data, str) and isinstance(mime, str):
            return {"type": btype, "data": data, "mimeType": mime}
    elif btype == "resource_link":
        uri, name = _get("uri"), _get("name")
        uri = str(uri) if uri is not None else None  # AnyUrl -> str
        if isinstance(uri, str) and isinstance(name, str):
            out = {"type": "resource_link", "uri": uri, "name": name}
            if isinstance(_get("description"), str):
                out["description"] = _get("description")
            if isinstance(_get("mimeType"), str):
                out["mimeType"] = _get("mimeType")
            return out
    elif btype == "resource":
        res = _get("resource")
        if isinstance(res, dict):
            ruri, rmime = res.get("uri"), res.get("mimeType")
            rtext, rblob = res.get("text"), res.get("blob")
        else:
            ruri = getattr(res, "uri", None)
            rmime = getattr(res, "mimeType", None)
            rtext = getattr(res, "text", None)
            rblob = getattr(res, "blob", None)
        # uri arrives as pydantic AnyUrl (a str subclass in the SDK dump but a
        # pydantic_core.Url instance in-memory), so coerce explicitly.
        ruri = str(ruri) if ruri is not None else None
        if isinstance(ruri, str) and (isinstance(rtext, str) or isinstance(rblob, str)):
            rdict: dict = {"uri": ruri}
            if isinstance(rmime, str):
                rdict["mimeType"] = rmime
            if isinstance(rtext, str):
                rdict["text"] = rtext
            else:
                rdict["blob"] = rblob
            return {"type": "resource", "resource": rdict}
    return None


def _rebuild_content(content) -> list[dict]:
    """Rebuild every upstream content block; unknown/degraded blocks become text."""
    out: list[dict] = []
    for c in content or []:
        rebuilt = _rebuild_content_block(c)
        if rebuilt is None:
            try:
                payload = c.model_dump(mode="json", by_alias=True) if hasattr(c, "model_dump") else c
            except Exception:
                payload = str(c)
            logger.warning("unsupported MCP content block degraded to text: %s", str(payload)[:200])
            rebuilt = {"type": "text", "text": json.dumps(payload, default=str)}
        out.append(rebuilt)
    return out


def _assert_wire_content(content: list) -> None:
    """Strict wire check: every block must be a spec content type with no nulls."""
    for i, b in enumerate(content):
        if not isinstance(b, dict):
            raise ValueError(f"content[{i}] is not an object")
        btype = b.get("type")
        if btype == "text":
            keys, req = _TEXT_KEYS, ("text",)
        elif btype in ("image", "audio"):
            keys, req = _DATA_KEYS, ("data", "mimeType")
        elif btype == "resource_link":
            keys, req = _RESOURCE_LINK_KEYS, ("uri", "name")
        elif btype == "resource":
            keys, req = _EMBEDDED_KEYS, ("resource",)
        else:
            raise ValueError(f"content[{i}] has unknown type {btype!r}")
        if set(b) - keys:
            raise ValueError(f"content[{i}] has unknown fields {sorted(set(b) - keys)}")
        for k in req:
            if b.get(k) is None or b.get(k) == "":
                raise ValueError(f"content[{i}].{k} missing/empty")
        if not _no_nulls(b):
            raise ValueError(f"content[{i}] contains a null field")
        if btype == "resource" and not isinstance(b["resource"], dict):
            raise ValueError(f"content[{i}].resource must be an object")


def _auth_headers(server: Server) -> dict[str, str]:
    if server.auth_type == "none" or not server.credential_encrypted:
        return {}
    try:
        cred = decrypt(server.credential_encrypted)
    except Exception:
        return {}
    if not cred:
        return {}
    if server.auth_type == "bearer":
        return {"Authorization": f"Bearer {cred}"}
    if server.auth_type == "header" and server.header_name:
        return {server.header_name: cred}
    return {}


def effective_call_timeout_seconds(server: Server, settings=None) -> float:
    """The call timeout that actually applies to one server, in seconds.

    A per-server timeout_ms differing from the LEGACY_TIMEOUT_MS sentinel (and
    from 0/None) is an explicit admin choice and wins. The sentinel — 10000, the
    column's historic DEFAULT that every pre-existing row and every seeded
    internal server carries — means "follow the global default"
    (config.call_timeout_seconds, Helm gateway.timeouts.callSeconds, ADR-089).
    Treating the old default as the sentinel (rather than rewriting stored rows
    with a migration) needs no data mutation, is idempotent, and keeps every
    explicit per-server value working; an admin who truly wants 10s pins 10001
    or any value inside the API's 1000..60000 range other than the sentinel.
    """
    if settings is None:
        settings = get_settings()
    if not server.timeout_ms or server.timeout_ms == LEGACY_TIMEOUT_MS:
        return settings.call_timeout_seconds
    return server.timeout_ms / 1000.0


async def proxy_call(
    server: Server,
    upstream_tool: str,
    arguments: dict,
    timeout_seconds: float | None = None,
) -> dict:
    """Proxy a single tools/call to one upstream via MCP SDK."""
    settings = get_settings()
    timeout_seconds = timeout_seconds or effective_call_timeout_seconds(server, settings)

    # SSRF DNS re-validate at request time (TOCTOU prevention)
    from urllib.parse import urlparse

    parsed = urlparse(server.url)
    host = parsed.hostname or ""
    # Allow internal suffixes to bypass private-net block (ClusterIP)
    allowed_suffixes = settings.allowed_host_suffix_list()
    is_internal = any(host.lower().endswith(s.lower()) or host.lower() == s.lstrip(".").lower() for s in allowed_suffixes) if allowed_suffixes else False
    if not is_internal and host and (host.startswith("urumi-") or "." not in host):
        is_internal = True
    if not is_internal:
        await resolve_and_validate(host)

    headers = _auth_headers(server)

    # Shared SSRF-safe factory (redirects never followed - ADR-047)
    from registry.validator import ssrf_safe_client_factory

    _factory = ssrf_safe_client_factory(timeout_seconds)

    async with (
        streamablehttp_client(server.url, headers=headers, httpx_client_factory=_factory) as (read, write, _meta),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(upstream_tool, arguments or {})
        # result is CallToolResult: content + isError (+ optional structuredContent)
        # Rebuild into minimal, spec-valid dicts — never model_dump() upstream
        # models, which leaks `"annotations": null` / `"meta": null` and breaks
        # strict MCP clients (MCP Inspector / TypeScript SDK).
        content = _rebuild_content(result.content)
        structured_content = getattr(result, "structuredContent", None)
        if not isinstance(structured_content, dict):
            # null / non-object structuredContent is invalid on the wire (TS SDK:
            # "expected record, received null"); only a JSON object is forwarded.
            structured_content = None
        payload = {"content": content, "isError": bool(getattr(result, "isError", False))}
        if structured_content is not None:
            payload["structuredContent"] = structured_content
        try:
            _assert_wire_content(payload["content"])
        except ValueError as exc:
            # Belt and braces: never let an invalid block reach the client.
            logger.warning("rebuilt tools/call content failed wire check (%s); degrading to text", exc)
            payload = {
                "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
                "isError": bool(payload.get("isError")),
            }
        return payload


async def call_tool_routed(
    db: AsyncSession,
    exposed_name: str,
    arguments: dict,
    *,
    timeout_seconds: float | None = None,
) -> dict:
    """Route by prefix, handle breaker/timeout, return upstream result.

    Raises on failure with appropriate HTTP-like exceptions (caller maps to JSON-RPC).
    """
    slug, upstream = split_exposed(exposed_name)
    # Request-shape guard (F2 pass): the MCP SDK crashes with an opaque
    # TaskGroup ExceptionGroup when arguments is not an object (e.g. the model
    # sent "arguments": "hello"), and the crash surfaced to users as a 502
    # "upstream error" while the audit blamed the upstream. This is a caller
    # mistake, not an upstream failure: reject it here as a validation error
    # before any network I/O, so the breaker and health never record it.
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError(f"Invalid arguments for tool '{exposed_name}': expected a JSON object")
    # lookup server by slug
    from sqlalchemy import select

    res = await db.execute(select(Server).where(Server.slug == slug))
    server = res.scalars().first()
    if not server:
        raise ValueError(f"Unknown server slug '{slug}' for tool '{exposed_name}'")
    if not server.enabled:
        raise ValueError(f"Server '{slug}' is disabled")
    if breaker.is_open(server.id):
        raise RuntimeError(f"Upstream {slug} circuit open")

    started = time.monotonic()
    try:
        result = await asyncio.wait_for(
            proxy_call(server, upstream, arguments, timeout_seconds=timeout_seconds),
            timeout=(timeout_seconds or effective_call_timeout_seconds(server)) + 1,
        )
        breaker.record_success(server.id)
        # keep status connected on success + record health timings
        record_success(server, latency_ms=int((time.monotonic() - started) * 1000))
        return result
    except ValueError:
        raise
    except McpError as exc:
        # The upstream ANSWERED with a JSON-RPC protocol error (e.g. -32602
        # invalid params): the transport is alive, so this is a request the
        # upstream rejected, not an upstream outage. Surface it as a validation
        # error (400 -32602) the model can act on, and never trip the breaker:
        # a responsive upstream is the opposite of a dead one.
        msg = getattr(exc.error, "message", None) or str(exc)
        raise ValueError(f"upstream rejected the request: {msg[:200]}") from exc
    except Exception as exc:
        category = classify(exc)
        if category == CATEGORY_TIMEOUT:
            # httpx read timeouts surface through the SDK's TaskGroup
            # ExceptionGroups, so they never arrived here as TimeoutError and
            # were mis-audited as upstream_error with a 502 (F2 pass). Re-raise
            # as TimeoutError so the caller maps them to 504 / outcome=timeout.
            breaker.record_failure(server.id)
            record_failure(server, CATEGORY_TIMEOUT, latency_ms=int((time.monotonic() - started) * 1000))
            raise TimeoutError(f"Upstream {slug} timed out") from exc
        # RuntimeError from the MCP/anyio transport counts as an upstream failure too:
        # without this, a proxy that fails with RuntimeError would hammer a dead
        # upstream forever without ever tripping the breaker (found by tests).
        breaker.record_failure(server.id)
        record_failure(server, category, latency_ms=int((time.monotonic() - started) * 1000))
        logger.warning("proxy_call failed for %s/%s category=%s", slug, upstream, category)
        raise UpstreamCallError(f"Upstream {slug} error: {exc}", category=category) from exc
