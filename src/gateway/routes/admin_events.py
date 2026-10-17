"""Admin action trail API (GET /api/admin-events, docs/DECISIONS.md ADR-034).

Admin-only, paginated, filters by actor (user id or email), action and date range.
Members get 403, anonymous 401. There is DELIBERATELY no POST/PUT/PATCH/DELETE on
this router: the trail is append-only, written only by the recorder in the same
transaction as the action it describes, and read here. Rows carry no secrets by
construction (audit/admin_events.py); this endpoint adds actor emails for display.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime

from audit.admin_events import query_admin_events
from auth.rbac import require_admin
from db.models import User
from db.session import get_db
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/admin-events", tags=["admin-events"])


@router.get("")
async def list_admin_events(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    # actor accepts a user id or an email; anything else is ignored, not a 500
    actor_filter: uuid.UUID | None = None
    if actor:
        with contextlib.suppress(Exception):
            actor_filter = uuid.UUID(actor)
        if actor_filter is None:
            res = await db.execute(select(User.id).where(User.email == actor.strip().lower()))
            actor_filter = res.scalar_one_or_none()

    from_dt = None
    to_dt = None
    if from_ts:
        with contextlib.suppress(Exception):
            from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
    if to_ts:
        with contextlib.suppress(Exception):
            to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))

    rows, total = await query_admin_events(
        db,
        actor_user_id=actor_filter,
        action=action,
        from_ts=from_dt,
        to_ts=to_dt,
        limit=limit,
        offset=offset,
    )
    # Batch-resolve actor emails for display (same pattern as /api/audit)
    actor_ids = {r.actor_user_id for r in rows if r.actor_user_id}
    email_by_id: dict = {}
    if actor_ids:
        u_res = await db.execute(select(User.id, User.email).where(User.id.in_(actor_ids)))
        for uid, email in u_res.all():
            email_by_id[uid] = email
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "events": [
            {
                "id": r.id,
                "ts": r.ts.isoformat(),
                "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
                "actor_email": email_by_id.get(r.actor_user_id),
                "action": r.action,
                "target_type": r.target_type,
                "target_ref": r.target_ref,
                "outcome": r.outcome,
                "details": r.details if r.details else {},
            }
            for r in rows
        ],
    }
