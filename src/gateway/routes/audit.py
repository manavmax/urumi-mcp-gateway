"""Audit log query (/api/audit)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from auth.rbac import get_current_user_via_session
from audit.crud import query_audit

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def get_audit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
    server: Optional[str] = Query(default=None),
    tool: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None),
    from_ts: Optional[str] = Query(default=None, alias="from"),
    to_ts: Optional[str] = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user_id: Optional[str] = Query(default=None),
):
    # parse timestamps
    from_dt = None
    to_dt = None
    if from_ts:
        try:
            from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        except Exception:
            pass
    if to_ts:
        try:
            to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        except Exception:
            pass
    uid_filter = None
    if user_id:
        try:
            uid_filter = uuid.UUID(user_id)
        except Exception:
            uid_filter = None

    rows, total = await query_audit(
        db,
        user_id=uid_filter,
        server_slug=server,
        tool=tool,
        from_ts=from_dt,
        to_ts=to_dt,
        outcome=outcome,
        limit=limit,
        offset=offset,
        current_user_id=user.id,
        is_admin=(user.role == "admin"),
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": [
            {
                "id": r.id,
                "ts": r.ts.isoformat(),
                "user_id": str(r.user_id) if r.user_id else None,
                "api_key_id": str(r.api_key_id) if r.api_key_id else None,
                "server_slug": r.server_slug,
                "tool_exposed_name": r.tool_exposed_name,
                "tool_upstream_name": r.tool_upstream_name,
                "request_id": str(r.request_id),
                "duration_ms": r.duration_ms,
                "outcome": r.outcome,
                "error_code": r.error_code,
                "client_ip": r.client_ip,
            }
            for r in rows
        ],
    }
