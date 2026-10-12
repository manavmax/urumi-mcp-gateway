"""tools/call routing via prefix slug__tool (docs/02 §3.2, 04 §6.2)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Server
from gw_mcp.aggregator import split_exposed
from gw_mcp.breaker import breaker
from registry.crypto import decrypt
from registry.validator import resolve_and_validate
from config import get_settings

logger = logging.getLogger("gateway.router")

ALLOWED_OUTCOMES = {"success", "upstream_error", "permission_denied", "timeout", "circuit_open", "validation_error"}


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


async def proxy_call(
    server: Server,
    upstream_tool: str,
    arguments: dict,
    timeout_seconds: float | None = None,
) -> dict:
    """Proxy a single tools/call to one upstream via MCP SDK."""
    settings = get_settings()
    timeout_seconds = timeout_seconds or (server.timeout_ms / 1000.0 if server.timeout_ms else settings.default_timeout_ms / 1000.0)

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

    def _factory(**_kwargs):
        return httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), follow_redirects=False)

    async with streamablehttp_client(server.url, headers=headers, httpx_client_factory=_factory) as (read, write, _meta):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(upstream_tool, arguments or {})
                # result is CallToolResult: content + isError
                # Normalize to dict for gateway response
                content = []
                for c in (result.content or []):
                    # c may be TextContent etc.
                    if hasattr(c, "model_dump"):
                        content.append(c.model_dump())
                    elif isinstance(c, dict):
                        content.append(c)
                    else:
                        # fallback: treat as text
                        content.append({"type": "text", "text": str(c)})
                return {"content": content, "isError": bool(getattr(result, "isError", False))}


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

    try:
        result = await asyncio.wait_for(
            proxy_call(server, upstream, arguments, timeout_seconds=timeout_seconds),
            timeout=(timeout_seconds or server.timeout_ms / 1000.0) + 1,
        )
        breaker.record_success(server.id)
        # keep status connected on success
        server.status = "Connected"
        server.last_error = None
        return result
    except asyncio.TimeoutError as exc:
        breaker.record_failure(server.id)
        server.status = "Unreachable"
        server.last_error = "timeout"
        raise TimeoutError(f"Upstream {slug} timed out") from exc
    except RuntimeError:
        raise
    except ValueError:
        raise
    except Exception as exc:
        breaker.record_failure(server.id)
        server.status = "Unreachable"
        server.last_error = str(exc)[:500]
        logger.warning("proxy_call failed for %s/%s: %s", slug, upstream, exc)
        raise RuntimeError(f"Upstream {slug} error: {exc}") from exc
