"""Admin CRUD for upstream servers (/api/servers) + admin "Check now" probe.

Observability (docs/11_OBSERVABILITY.md): the health-tracking columns
(last_checked_at, last_ok_at, last_latency_ms, last_error_category) are returned
to ADMINS only; members see status without category details. last_error holds only
a safe human label derived from the category - never raw exception text, which
could embed a URL with credentials, a header or a token.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from auth.rbac import get_current_user_via_session, require_admin, verify_csrf
from config import get_settings
from db.models import Server
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from registry.crud import create_server, delete_server, get_server, list_servers, update_server
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/servers", tags=["servers"])


class ServerCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    url: str
    auth_type: str = Field(default="none", pattern=r"^(none|bearer|header)$")
    header_name: str | None = None
    credential: str | None = None  # plaintext, encrypted server-side
    timeout_ms: int = Field(default=10000, ge=1000, le=60000)
    enabled: bool = True


class ServerUpdate(BaseModel):
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$")
    url: str | None = None
    auth_type: str | None = Field(default=None, pattern=r"^(none|bearer|header)$")
    header_name: str | None = None
    credential: str | None = None
    timeout_ms: int | None = Field(default=None, ge=1000, le=60000)
    enabled: bool | None = None


def _server_out(s: Server, is_admin: bool = True) -> dict:
    out = {
        "id": str(s.id),
        "slug": s.slug,
        "url": s.url,
        "auth_type": s.auth_type,
        "header_name": s.header_name,
        "credential": "***" if s.credential_encrypted else None,  # never leak
        "enabled": s.enabled,
        "status": s.status,
        "last_error": s.last_error,  # safe human label only, never raw text
        "timeout_ms": s.timeout_ms,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
    if is_admin:
        # admins see the health-tracking details; members get status only
        out["last_checked_at"] = s.last_checked_at.isoformat() if s.last_checked_at else None
        out["last_ok_at"] = s.last_ok_at.isoformat() if s.last_ok_at else None
        out["last_latency_ms"] = s.last_latency_ms
        out["last_error_category"] = s.last_error_category
    else:
        # members see status only - drop even the safe last_error label
        out.pop("last_error")
    return out


@router.get("")
async def list_servers_route(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    rows = await list_servers(db, include_disabled=True)
    return {"servers": [_server_out(r, is_admin=user.role == "admin") for r in rows]}


@router.post("", status_code=201)
async def create_server_route(
    body: ServerCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    verify_csrf(request)
    settings = get_settings()
    try:
        srv = await create_server(
            db,
            slug=body.slug,
            url=body.url,
            auth_type=body.auth_type,
            header_name=body.header_name,
            credential=body.credential,
            timeout_ms=body.timeout_ms,
            enabled=body.enabled,
            allowed_host_suffixes=settings.allowed_host_suffix_list(),
            allowed_domains=settings.allowed_domains_list(),
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _server_out(srv, is_admin=True)


@router.get("/{server_id}")
async def get_server_route(
    server_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    srv = await get_server(db, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="server not found")
    return _server_out(srv, is_admin=user.role == "admin")


@router.post("/{server_id}/check")
async def check_server_route(
    server_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Admin "Check now": force an immediate health probe of one server.

    Rate limited to one per server per 5 seconds (in-memory). CSRF-protected
    like every other mutating dashboard endpoint. Returns the fresh server row
    with health-tracking details.
    """
    verify_csrf(request)
    if not _check_rate_limit(str(server_id)):
        raise HTTPException(status_code=429, detail="check now rate limited (one per 5s)")
    srv = await get_server(db, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="server not found")
    settings = get_settings()
    from gw_mcp.aggregator import fetch_and_cache_tools
    from gw_mcp.categorize import classify
    from gw_mcp.health_state import record_failure, record_success

    started = time.monotonic()
    try:
        await asyncio.wait_for(
            fetch_and_cache_tools(db, srv, timeout_seconds=settings.health_timeout_seconds),
            timeout=settings.health_timeout_seconds + 2,
        )
    except Exception as exc:
        record_failure(srv, classify(exc), latency_ms=int((time.monotonic() - started) * 1000))
    else:
        record_success(srv, latency_ms=int((time.monotonic() - started) * 1000))
    await db.commit()
    return _server_out(srv, is_admin=True)


# ---- check-now rate limiter (in-memory, one per server per 5s) ----
_check_buckets: dict[str, float] = {}


def _check_rate_limit(key: str) -> bool:
    now = time.monotonic()
    last = _check_buckets.get(key)
    if last is not None and now - last < 5.0:
        return False
    _check_buckets[key] = now
    return True


@router.patch("/{server_id}")
async def patch_server_route(
    server_id: uuid.UUID,
    body: ServerUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    verify_csrf(request)
    srv = await get_server(db, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="server not found")
    settings = get_settings()
    try:
        srv = await update_server(
            db,
            srv,
            slug=body.slug,
            url=body.url,
            auth_type=body.auth_type,
            header_name=body.header_name,
            credential=body.credential,
            timeout_ms=body.timeout_ms,
            enabled=body.enabled,
            allowed_host_suffixes=settings.allowed_host_suffix_list(),
            allowed_domains=settings.allowed_domains_list(),
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _server_out(srv, is_admin=True)


@router.post("/{server_id}/disable")
async def disable_server_route(
    server_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    verify_csrf(request)
    srv = await get_server(db, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="server not found")
    srv.enabled = False
    srv.status = "Disabled"
    await db.commit()
    return _server_out(srv, is_admin=True)


@router.post("/{server_id}/enable")
async def enable_server_route(
    server_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    verify_csrf(request)
    srv = await get_server(db, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="server not found")
    srv.enabled = True
    srv.status = "Unknown"
    await db.commit()
    return _server_out(srv, is_admin=True)


@router.delete("/{server_id}", status_code=204)
async def delete_server_route(
    server_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    verify_csrf(request)
    srv = await get_server(db, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="server not found")
    await delete_server(db, srv)
    await db.commit()
    return None
