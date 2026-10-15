"""Overview aggregates for the dashboard (/api/stats).

Window: a named range, default the approved 14 days. Admin = every user's
calls; member = only their own audit rows (same scoping rule as /api/audit).
All queries are parameterized SQLAlchemy selects; no raw SQL, no argument
values or credentials in the response.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from auth.rbac import get_current_user_via_session
from db.models import ApiKey, AuditLog, Server, Tool, User
from db.session import get_db
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/stats", tags=["stats"])

RANGE_WINDOWS: dict[str, timedelta] = {
    "day": timedelta(days=1),
    "week": timedelta(days=7),
    "month": timedelta(days=30),
    "14d": timedelta(days=14),
}

# Percentiles and the per-day series are computed in Python over the window's
# rows: portable across Postgres (prod) and sqlite (tests), bounded by a cap.
DURATION_FETCH_CAP = 50000


def _percentile(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        return 0
    idx = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[idx]


@router.get("")
async def get_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
    range: str = Query(default="14d", description="day, week, month or 14d"),
):
    window = RANGE_WINDOWS.get(range, RANGE_WINDOWS["14d"])
    now = datetime.now(UTC)
    start = now - window
    is_admin = user.role == "admin"

    # Scope: non-admins only ever see their own calls (same rule as /api/audit).
    scope = [AuditLog.ts >= start]
    if not is_admin:
        scope.append(AuditLog.user_id == user.id)

    # One bounded fetch covers counts, per-day, durations and top tools.
    res = await db.execute(
        select(
            AuditLog.ts,
            AuditLog.duration_ms,
            AuditLog.outcome,
            AuditLog.tool_exposed_name,
            AuditLog.api_key_id,
        )
        .where(*scope)
        .limit(DURATION_FETCH_CAP)
    )
    rows = res.all()

    by_outcome: Counter = Counter()
    durations: list[int] = []
    tool_counter: Counter = Counter()
    per_day: dict[str, dict] = {}
    own_api_key_calls = 0
    for ts, duration_ms, outcome, tool_name, api_key_id in rows:
        by_outcome[outcome] += 1
        durations.append(duration_ms)
        tool_counter[tool_name] += 1
        day = ts.date().isoformat()
        bucket = per_day.setdefault(day, {"calls": 0, "errors": 0, "durations": []})
        bucket["calls"] += 1
        if outcome != "success":
            bucket["errors"] += 1
        bucket["durations"].append(duration_ms)
        if api_key_id is not None:
            own_api_key_calls += 1

    calls = sum(by_outcome.values())
    success = by_outcome.get("success", 0)
    errors = calls - success
    success_rate = round(100.0 * success / calls, 1) if calls else None
    sorted_all = sorted(durations)

    # Previous window of equal length, for the hero delta.
    prev_scope = [AuditLog.ts >= start - window, AuditLog.ts < start]
    if not is_admin:
        prev_scope.append(AuditLog.user_id == user.id)
    prev_res = await db.execute(select(func.count()).select_from(AuditLog).where(*prev_scope))
    prev_calls = int(prev_res.scalar() or 0)

    # Fill every day of the window (including empty days) so the chart has a
    # complete series with no gaps.
    per_day_series: list[dict] = []
    day = (now - window).date()
    while day <= now.date():
        key = day.isoformat()
        bucket = per_day.get(key)
        if bucket:
            per_day_series.append({
                "date": key,
                "calls": bucket["calls"],
                "errors": bucket["errors"],
                "p95_ms": _percentile(sorted(bucket["durations"]), 0.95),
            })
        else:
            per_day_series.append({"date": key, "calls": 0, "errors": 0, "p95_ms": 0})
        day += timedelta(days=1)

    servers_res = await db.execute(select(Server.status, func.count()).group_by(Server.status))
    by_status = {status: int(count) for status, count in servers_res.all()}

    tools_res = await db.execute(
        select(func.count())
        .select_from(Tool)
        .join(Server, Tool.server_id == Server.id)
        .where(Server.enabled.is_(True))
    )
    tools_exposed = int(tools_res.scalar() or 0)

    top_tools = [{"tool": tool, "calls": n} for tool, n in tool_counter.most_common(5)]

    out = {
        "range": range,
        "window_days": max(1, int(window.total_seconds() // 86400)),
        "servers": {"by_status": by_status},
        "tools_exposed": tools_exposed,
        "audit": {
            "calls": calls,
            "prev_calls": prev_calls,
            "success": by_outcome.get("success", 0),
            "errors": errors,
            "success_rate": success_rate,
            "p50_ms": _percentile(sorted_all, 0.50),
            "p95_ms": _percentile(sorted_all, 0.95),
            "by_outcome": dict(by_outcome),
            "per_day": per_day_series,
            "top_tools": top_tools,
        },
    }
    if is_admin:
        users_res = await db.execute(select(func.count()).select_from(User))
        out["users_total"] = int(users_res.scalar() or 0)
    else:
        keys_res = await db.execute(
            select(func.count())
            .select_from(ApiKey)
            .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
        )
        out["own_keys_active"] = int(keys_res.scalar() or 0)
        out["own_api_key_calls"] = own_api_key_calls
    return out
