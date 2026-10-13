"""Admin CRUD for upstream servers (/api/servers)."""

from __future__ import annotations

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


def _server_out(s: Server) -> dict:
    return {
        "id": str(s.id),
        "slug": s.slug,
        "url": s.url,
        "auth_type": s.auth_type,
        "header_name": s.header_name,
        "credential": "***" if s.credential_encrypted else None,  # never leak
        "enabled": s.enabled,
        "status": s.status,
        "last_error": s.last_error,
        "timeout_ms": s.timeout_ms,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("")
async def list_servers_route(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    rows = await list_servers(db, include_disabled=True)
    return {"servers": [_server_out(r) for r in rows]}


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
        raise HTTPException(status_code=400, detail=str(exc))
    return _server_out(srv)


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
    return _server_out(srv)


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
        raise HTTPException(status_code=400, detail=str(exc))
    return _server_out(srv)


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
    return _server_out(srv)


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
    return _server_out(srv)


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
