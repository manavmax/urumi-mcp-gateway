"""Next-best-action banner state (/api/alerts, docs/11_OBSERVABILITY.md §3).

Admin payload: one row per ALERTING enabled server, either unreachable (with
category + unreachable_since) or with an error rate over the last hour above 20%
AND at least 5 calls in that hour. Member payload: only the affected slugs, no
internal reasons. Empty when everything is healthy.

Never leaks a credential, a header or a token: only the category token and the
server slug are ever in the response.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from auth.rbac import get_current_user_via_session
from db.models import AuditLog, Server
from db.session import get_db
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Banner rule: an enabled server whose error rate over the last hour is above
# 20% with at least 5 calls also triggers the banner (docs/11_OBSERVABILITY.md §3).
HIGH_ERROR_RATE_PCT = 20.0
HIGH_ERROR_MIN_CALLS = 5
HOUR = timedelta(hours=1)


async def _alerting_servers(db: AsyncSession) -> list[dict]:
    """Admin alert rows: unreachable servers + last-hour high-error-rate servers."""
    servers = list((await db.execute(select(Server).where(Server.enabled.is_(True)))).scalars().all())
    now = datetime.now(UTC)
    hour_start = now - HOUR

    # last-hour calls/errors per enabled server (exact SQL aggregate)
    err_res = await db.execute(
        select(AuditLog.server_slug, AuditLog.outcome, func.count())
        .where(AuditLog.ts >= hour_start, AuditLog.server_slug.in_([s.slug for s in servers]))
        .group_by(AuditLog.server_slug, AuditLog.outcome)
    )
    hourly: dict[str, dict] = {}
    for slug, outcome, n in err_res.all():
        row = hourly.setdefault(slug, {"calls": 0, "errors": 0})
        row["calls"] += int(n)
        if outcome != "success":
            row["errors"] += int(n)

    rows: list[dict] = []
    for s in servers:
        if s.status == "Unreachable":
            rows.append(
                {
                    "slug": s.slug,
                    "kind": "unreachable",
                    "status": s.status,
                    "category": s.last_error_category,
                    "reason": s.last_error or (s.last_error_category or "unreachable"),
                    "unreachable_since": s.last_ok_at.isoformat() if s.last_ok_at else (s.last_checked_at.isoformat() if s.last_checked_at else None),
                }
            )
            continue
        h = hourly.get(s.slug, {"calls": 0, "errors": 0})
        if h["calls"] >= HIGH_ERROR_MIN_CALLS and h["errors"] > 0 and (100.0 * h["errors"] / h["calls"]) > HIGH_ERROR_RATE_PCT:
            rows.append(
                {
                    "slug": s.slug,
                    "kind": "high_error_rate",
                    "status": s.status,
                    "category": "http_error",
                    "reason": f"{round(100.0 * h['errors'] / h['calls'], 1)}% error rate in the last hour",
                    "calls_1h": h["calls"],
                    "errors_1h": h["errors"],
                    "unreachable_since": None,
                }
            )
    return rows


@router.get("")
async def get_alerts(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user_via_session)):
    rows = await _alerting_servers(db)
    if user.role == "admin":
        return {"admin": rows}
    # members: calm notice with the affected slugs only, no internal reasons
    return {"member": {"slugs": [r["slug"] for r in rows]}}
