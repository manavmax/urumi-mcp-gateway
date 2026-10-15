"""Audit log query (/api/audit) and admin CSV export (/api/audit/export)."""

from __future__ import annotations

import contextlib
import csv
import io
import uuid
from datetime import datetime

from audit.crud import query_audit
from auth.rbac import get_current_user_via_session
from db.models import User
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def get_audit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
    server: str | None = Query(default=None),
    tool: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user_id: str | None = Query(default=None),
):
    # parse timestamps (best-effort: an unparseable filter is dropped, not a 500)
    from_dt = None
    to_dt = None
    if from_ts:
        with contextlib.suppress(Exception):
            from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
    if to_ts:
        with contextlib.suppress(Exception):
            to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
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
    # Batch-resolve user emails for display (auditor-friendly; no extra N+1 query)
    user_ids = {r.user_id for r in rows if r.user_id}
    email_by_id: dict = {}
    if user_ids:
        u_res = await db.execute(select(User.id, User.email).where(User.id.in_(user_ids)))
        for uid, email in u_res.all():
            email_by_id[uid] = email
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": [
            {
                "id": r.id,
                "ts": r.ts.isoformat(),
                "user_id": str(r.user_id) if r.user_id else None,
                "user_email": email_by_id.get(r.user_id),
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


CSV_HEADER = ["ts", "user_email", "server_slug", "tool_exposed_name", "tool_upstream_name",
              "request_id", "duration_ms", "outcome", "error_code", "client_ip"]
CSV_ROW_CAP = 5000


@router.get("/export")
async def export_audit_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
    server: str | None = Query(default=None),
    tool: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    user_id: str | None = Query(default=None),
):
    """Admin-only CSV of the current filters. Hard-capped at 5000 rows; audit
    rows store no tool arguments, so no argument values can leak by design."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")

    from_dt = None
    to_dt = None
    if from_ts:
        with contextlib.suppress(Exception):
            from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
    if to_ts:
        with contextlib.suppress(Exception):
            to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
    uid_filter = None
    if user_id:
        with contextlib.suppress(Exception):
            uid_filter = uuid.UUID(user_id)
    else:
        uid_filter = None

    rows, _total = await query_audit(
        db,
        user_id=uid_filter,
        server_slug=server,
        tool=tool,
        from_ts=from_dt,
        to_ts=to_dt,
        outcome=outcome,
        limit=CSV_ROW_CAP,
        offset=0,
        current_user_id=user.id,
        is_admin=True,
    )

    user_ids = {r.user_id for r in rows if r.user_id}
    email_by_id: dict = {}
    if user_ids:
        u_res = await db.execute(select(User.id, User.email).where(User.id.in_(user_ids)))
        for uid, email in u_res.all():
            email_by_id[uid] = email

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for r in rows[:CSV_ROW_CAP]:
        writer.writerow([
            r.ts.isoformat(),
            email_by_id.get(r.user_id, ""),
            r.server_slug,
            r.tool_exposed_name,
            r.tool_upstream_name,
            str(r.request_id),
            r.duration_ms,
            r.outcome,
            r.error_code or "",
            r.client_ip or "",
        ])
    return Response(
        content="".join(["\ufeff", buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-export.csv"'},
    )
