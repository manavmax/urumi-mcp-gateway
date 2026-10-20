"""MCP aggregation: fan-out tools/list + storage + prefix (docs/02 §3, 04 §6)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from db.models import Server, Tool
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from registry.crypto import decrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("gateway.aggregator")


def exposed_name(slug: str, upstream_name: str) -> str:
    return f"{slug}__{upstream_name}"


def split_exposed(name: str) -> tuple[str, str]:
    if "__" not in name:
        raise ValueError(f"tool name '{name}' missing slug prefix (expected slug__tool)")
    slug, orig = name.split("__", 1)
    if not slug or not orig:
        raise ValueError(f"invalid tool name '{name}'")
    return slug, orig


def _auth_headers(server: Server) -> dict[str, str]:
    if server.auth_type == "none" or not server.credential_encrypted:
        return {}
    try:
        cred = decrypt(server.credential_encrypted)
    except Exception:
        logger.warning("failed to decrypt credential for %s", server.slug)
        return {}
    if not cred:
        return {}
    if server.auth_type == "bearer":
        return {"Authorization": f"Bearer {cred}"}
    if server.auth_type == "header" and server.header_name:
        return {server.header_name: cred}
    return {}


async def _fetch_tools_for_server(server: Server, timeout_seconds: float = 8.0) -> list[dict[str, Any]]:
    """Call tools/list on one upstream via MCP SDK; return list of tool dicts."""
    from urllib.parse import urlparse as _urlparse

    from config import get_settings

    # Internal service names bypass SSRF DNS block at proxy time; fan-out also skips it here
    # so health-check/aggregation can reach ClusterIP services (10.x).
    parsed = _urlparse(server.url)
    host = parsed.hostname or ""
    allowed_suffixes = get_settings().allowed_host_suffix_list()
    is_internal = any(host.lower().endswith(s.lower()) or host.lower() == s.lstrip(".").lower() for s in allowed_suffixes) if allowed_suffixes else False
    if not is_internal and host:
        from registry.validator import resolve_and_validate
        # bare names and urumi-* are in-cluster ClusterIP services — never SSRF-block them
        if host.startswith("urumi-") or "." not in host:
            is_internal = True
        else:
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
        result = await session.list_tools()
        out = []
        for t in result.tools:
            out.append(
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema if isinstance(t.inputSchema, dict) else (t.inputSchema or {}),
                    "annotations": getattr(t, "annotations", None),
                }
            )
        return out


async def fetch_and_cache_tools(db: AsyncSession, server: Server, timeout_seconds: float = 8.0) -> list[Tool]:
    """Fetch from upstream and upsert into tools table with prefix. Returns Tool rows."""
    try:
        upstream_tools = await asyncio.wait_for(_fetch_tools_for_server(server, timeout_seconds), timeout=timeout_seconds + 2)
    except Exception as exc:
        logger.warning("tools/list failed for %s (%s): %s", server.slug, server.url, exc)
        raise

    # Remove stale tools for this server not in new set?
    # Instead: upsert new, delete removed.
    new_names = {t["name"] for t in upstream_tools}
    # existing
    res = await db.execute(select(Tool).where(Tool.server_id == server.id))
    existing = {t.upstream_name: t for t in res.scalars().all()}
    # delete removed
    for name, row in list(existing.items()):
        if name not in new_names:
            await db.delete(row)
    # upsert
    result_rows: list[Tool] = []
    for t in upstream_tools:
        ename = exposed_name(server.slug, t["name"])
        desc = f"[{server.slug}] {t['description']}" if t["description"] else f"[{server.slug}] {t['name']}"
        schema = t["inputSchema"] or {"type": "object", "properties": {}}
        row = existing.get(t["name"])
        if row:
            row.exposed_name = ename
            row.description = desc
            row.input_schema = schema
        else:
            row = Tool(
                server_id=server.id,
                upstream_name=t["name"],
                exposed_name=ename,
                description=desc,
                input_schema=schema,
            )
            db.add(row)
        result_rows.append(row)
    await db.flush()
    return result_rows


async def _cache_fallback(db: AsyncSession, s: Server, err: str) -> list[dict] | None:
    """Last-known tool snapshot for one failed server, or None when there is none.

    The health loop keeps the tools table warm (it runs fetch_and_cache_tools every
    interval), so when a single upstream times out or its breaker is open we serve
    that snapshot instead of silently dropping the server's tools from the merged
    tools/list. Without this, one slow upstream makes every MCP client see fewer
    tools than are actually allowed (member AND admin alike), which external
    clients like Cursor surface as "tools disappeared".

    A failed fetch can leave the shared request session in PendingRollback (its
    own flush blew up); roll that back first so the cache read can run. If the
    read itself fails, give up and let the caller report the plain error.
    """
    try:
        if not db.is_active:
            await db.rollback()
        cached = await list_cached_tools(db, [s.id])
    except Exception:
        return None
    return cached or None


async def fanout_list_tools(db: AsyncSession, servers: list[Server], timeout_seconds: float = 8.0) -> tuple[list[dict], list[dict]]:
    """Fan-out tools/list across enabled servers with isolation (gather+return_exceptions).

    A server whose live fetch fails (timeout, breaker open) still contributes its
    last-known cached tools, with a warning entry carrying "stale_cache": True.
    Returns (tools, warnings) where tools are exposed tool dicts.
    """
    from gw_mcp.breaker import breaker

    async def fetch_one(s: Server):
        from gw_mcp.categorize import classify
        from gw_mcp.health_state import record_failure, record_success

        if breaker.is_open(s.id):
            cached = await _cache_fallback(db, s, "circuit open")
            if cached is not None:
                return {"server": s.slug, "tools": cached, "stale": True, "error": "circuit open"}
            return {"server": s.slug, "error": "circuit open", "circuit": True}
        started = time.monotonic()
        try:
            rows = await fetch_and_cache_tools(db, s, timeout_seconds=timeout_seconds)
            # convert rows to exposed dicts
            tools = []
            for r in rows:
                tools.append(
                    {
                        "name": r.exposed_name,
                        "description": r.description,
                        "inputSchema": r.input_schema,
                    }
                )
            # mark connected + record health timings
            record_success(s, latency_ms=int((time.monotonic() - started) * 1000))
            breaker.record_success(s.id)
            return {"server": s.slug, "tools": tools}
        except Exception as exc:
            breaker.record_failure(s.id)
            record_failure(s, classify(exc), latency_ms=int((time.monotonic() - started) * 1000))
            cached = await _cache_fallback(db, s, s.last_error or "upstream error")
            if cached is not None:
                return {"server": s.slug, "tools": cached, "stale": True, "error": s.last_error or "upstream error"}
            return {"server": s.slug, "error": s.last_error}

    results = await asyncio.gather(*[fetch_one(s) for s in servers], return_exceptions=True)
    all_tools: list[dict] = []
    warnings: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            warnings.append({"error": str(r)[:500]})
            continue
        if "tools" in r:
            all_tools.extend(r.get("tools", []))
            if r.get("stale"):
                warnings.append({"server": r.get("server"), "error": r.get("error") or "upstream error", "stale_cache": True})
            continue
        if "error" in r:
            warnings.append({"server": r.get("server"), "error": r["error"]})
    await db.flush()
    return all_tools, warnings


async def list_cached_tools(db: AsyncSession, server_ids: list[uuid.UUID] | None = None) -> list[dict]:
    """Return cached tools (no upstream call). Used for fast tools/list when health loop keeps cache warm."""
    q = select(Tool).order_by(Tool.exposed_name)
    if server_ids is not None:
        if not server_ids:
            return []
        q = q.where(Tool.server_id.in_(server_ids))
    res = await db.execute(q)
    rows = res.scalars().all()
    return [{"name": r.exposed_name, "description": r.description, "inputSchema": r.input_schema} for r in rows]
