"""Aggregated catalog for dashboard chat (/api/tools)."""

from __future__ import annotations

from auth.rbac import get_current_user_via_session
from db.models import Server
from db.session import get_db
from fastapi import APIRouter, Depends, Request
from gw_mcp.aggregator import fanout_list_tools, list_cached_tools
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def get_tools(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user_via_session)):
    res = await db.execute(select(Server).where(Server.enabled.is_(True)))
    servers = list(res.scalars().all())
    if not servers:
        return {"tools": [], "warnings": []}
    # try live fan-out; fallback to cache. The fan-out uses the global list
    # timeout (gateway.timeouts.listSeconds, default 3s, ADR-089).
    try:
        tools, warnings = await fanout_list_tools(db, servers)
    except Exception:
        tools = await list_cached_tools(db, [s.id for s in servers])
        warnings = []
    # per-role deny rules: members lose denied tools, admins see everything
    from gw_mcp.permissions import filter_tools_for_user

    tools = await filter_tools_for_user(db, user, tools)
    return {"tools": tools, "warnings": warnings}
