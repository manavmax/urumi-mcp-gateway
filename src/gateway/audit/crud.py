"""Audit query helpers."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog


async def query_audit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    server_slug: str | None = None,
    tool: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    outcome: str | None = None,
    limit: int = 100,
    offset: int = 0,
    current_user_id: uuid.UUID | None = None,
    is_admin: bool = False,
) -> tuple[list[AuditLog], int]:
    q = select(AuditLog).order_by(AuditLog.ts.desc())
    count_q = select(AuditLog)

    # Non-admins only see own rows
    if not is_admin and current_user_id:
        q = q.where(AuditLog.user_id == current_user_id)
        count_q = count_q.where(AuditLog.user_id == current_user_id)
    elif user_id and is_admin:
        q = q.where(AuditLog.user_id == user_id)
        count_q = count_q.where(AuditLog.user_id == user_id)

    if server_slug:
        q = q.where(AuditLog.server_slug == server_slug)
        count_q = count_q.where(AuditLog.server_slug == server_slug)
    if tool:
        q = q.where(AuditLog.tool_exposed_name == tool)
        count_q = count_q.where(AuditLog.tool_exposed_name == tool)
    if outcome:
        q = q.where(AuditLog.outcome == outcome)
        count_q = count_q.where(AuditLog.outcome == outcome)
    if from_ts:
        q = q.where(AuditLog.ts >= from_ts)
        count_q = count_q.where(AuditLog.ts >= from_ts)
    if to_ts:
        q = q.where(AuditLog.ts <= to_ts)
        count_q = count_q.where(AuditLog.ts <= to_ts)

    # count
    from sqlalchemy import func

    total_res = await db.execute(select(func.count()).select_from(count_q.subquery()))
    total = total_res.scalar() or 0

    q = q.limit(limit).offset(offset)
    res = await db.execute(q)
    rows = list(res.scalars().all())
    return rows, total
