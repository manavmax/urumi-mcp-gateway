"""Admin tool-permissions policy API (/api/permissions, ADR-033).

Admin-only (admins always have all tools; members get 403). GET lists every server +
its tools with the member-denied flag; PUT replaces the member deny policy and is
CSRF-protected. Unknown tool or server names are rejected (422).
"""

from __future__ import annotations

from audit.admin_events import bounded_diff, record_admin_event
from auth.rbac import require_admin, verify_csrf
from db.models import Server, Tool, ToolPermission
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/permissions", tags=["permissions"])

ROLE = "member"


class DenyRuleIn(BaseModel):
    server_slug: str
    tool_name: str | None = None  # None = whole server


class PermissionsPutBody(BaseModel):
    rules: list[DenyRuleIn] = []


async def _policy_payload(db: AsyncSession) -> dict:
    """Shared shape for GET and PUT responses: servers + tools + denied flags + count."""
    servers = list((await db.execute(select(Server))).scalars().all())
    all_tools = list((await db.execute(select(Tool))).scalars().all())
    rules = list((await db.execute(select(ToolPermission).where(ToolPermission.role == ROLE))).scalars().all())

    deny: set[str] = set()
    for r in rules:
        deny.add(f"{r.server_slug}__*" if r.tool_name is None else r.tool_name)

    server_rows = []
    restricted_count = 0
    for s in sorted(servers, key=lambda x: x.slug):
        tool_rows = []
        for t in sorted((t for t in all_tools if t.server_id == s.id), key=lambda x: x.exposed_name):
            denied = f"{s.slug}__*" in deny or t.exposed_name in deny
            if denied:
                restricted_count += 1
            tool_rows.append({"name": t.exposed_name, "description": t.description, "member_denied": denied})
        server_rows.append({"slug": s.slug, "enabled": s.enabled, "status": s.status, "tools": tool_rows})
    return {"servers": server_rows, "restricted_count": restricted_count}


@router.get("")
async def get_permissions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Admin: current member deny policy + the tool inventory it applies to."""
    return await _policy_payload(db)


@router.put("")
async def put_permissions(
    body: PermissionsPutBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Replace the member deny policy. Admin-only, CSRF-protected, validates names."""
    verify_csrf(request)

    servers = list((await db.execute(select(Server))).scalars().all())
    by_slug = {s.slug: s for s in servers}
    all_tools = list((await db.execute(select(Tool))).scalars().all())
    tools_by_server: dict[str, set[str]] = {}
    for s in servers:
        tools_by_server[s.slug] = {t.exposed_name for t in all_tools if t.server_id == s.id}

    for rule in body.rules:
        if rule.server_slug not in by_slug:
            raise HTTPException(status_code=422, detail=f"unknown server '{rule.server_slug}'")
        if rule.tool_name is not None and rule.tool_name not in tools_by_server[rule.server_slug]:
            raise HTTPException(status_code=422, detail=f"unknown tool '{rule.tool_name}' for server '{rule.server_slug}'")

    # replace the member policy wholesale (single Save button semantics)
    old = (await db.execute(select(ToolPermission).where(ToolPermission.role == ROLE))).scalars().all()
    old_keys = {f"{r.server_slug}__*" if r.tool_name is None else r.tool_name for r in old}
    new_keys = {f"{r.server_slug}__*" if r.tool_name is None else r.tool_name for r in body.rules}
    for r in old:
        await db.delete(r)
    await db.flush()
    for rule in body.rules:
        db.add(ToolPermission(role=ROLE, server_slug=rule.server_slug, tool_name=rule.tool_name, created_by=user.id))
    # ONE permission.change event per PUT with the direction diff:
    # "added" = rules newly denied, "removed" = rules lifted (allowed again)
    record_admin_event(
        db,
        actor_user_id=user.id,
        action="permission.change",
        target_type="permission",
        target_ref=ROLE,
        details=bounded_diff(sorted(new_keys - old_keys), sorted(old_keys - new_keys)),
    )
    await db.commit()

    return await _policy_payload(db)
