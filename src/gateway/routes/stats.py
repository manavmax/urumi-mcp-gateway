"""Overview aggregates for the dashboard (/api/stats).

Window: a named range, default the approved 14 days. Admin = every user's
calls; member = only their own audit rows (same scoping rule as /api/audit).
Counts are exact SQL aggregates; only the duration percentiles come from a
bounded sample (newest rows first, so the cap degrades deterministically).
All queries are parameterized SQLAlchemy selects; no raw SQL, no argument
values or credentials in the response. Admins additionally get by_server
(docs/11_OBSERVABILITY.md §2) and top_tools (top exposed tool names by
calls) - members never receive either.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from auth.rbac import get_current_user_via_session
from db.models import ApiKey, AuditLog
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

# Percentiles are computed in Python over the newest rows of the window:
# portable across Postgres (prod) and sqlite (tests), bounded by a cap. Counts
# and the per-day series are exact SQL aggregates and never see the cap.
DURATION_FETCH_CAP = 50000

# by_server sparkline: daily points over the range, capped at 14 (the 7 or
# 14-point sparkline per server, docs/11_OBSERVABILITY.md §2).
SPARKLINE_MAX_POINTS = 14

# Admin top-tools aggregate for the Overview page (docs/POLISH_DASHBOARD.md):
# top N exposed tool names by calls over the selected window. Counts only -
# never argument values or credentials.
TOP_TOOLS_MAX = 6


def _percentile(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        return 0
    idx = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[idx]


def _day_key(value) -> str:
    """func.date() yields a date object on Postgres and a string on sqlite."""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _sparkline_from_days(
    days: dict[str, dict],
    total_days: int,
    now: datetime,
) -> list[dict]:
    """Per-server daily series over the selected range, capped at the newest
    SPARKLINE_MAX_POINTS days. Empty days are filled with zeros so the chart
    has no gaps (same rule as the headline per-day series)."""
    count = min(max(1, total_days), SPARKLINE_MAX_POINTS)
    keys: list[str] = []
    cursor = now.date()
    first_day = (now - timedelta(days=total_days)).date()
    while cursor >= first_day and len(keys) < count:
        keys.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    keys.reverse()
    return [
        {
            "date": key,
            "calls": days.get(key, {}).get("calls", 0),
            "errors": days.get(key, {}).get("errors", 0),
        }
        for key in keys
    ]


async def _by_server(db: AsyncSession, start: datetime, now: datetime, window: timedelta) -> list[dict]:
    """Admin per-server aggregates (docs/11_OBSERVABILITY.md §2).

    calls/errors and the sparkline are exact SQL group-bys; p50/p95 come from the
    same bounded newest-first duration sample as the headline percentiles.
    Sorted by calls, descending.
    """
    scope = [AuditLog.ts >= start]

    # exact per-server outcome counts (one group-by, no row fetch)
    outcome_res = await db.execute(
        select(AuditLog.server_slug, AuditLog.outcome, func.count())
        .where(*scope)
        .group_by(AuditLog.server_slug, AuditLog.outcome)
    )
    per_server: dict[str, dict] = {}
    for slug, outcome, n in outcome_res.all():
        row = per_server.setdefault(slug, {"calls": 0, "errors": 0, "days": {}, "durations": []})
        row["calls"] += int(n)
        if outcome != "success":
            row["errors"] += int(n)

    # exact per-day per-server counts for the sparkline (one group-by)
    day_res = await db.execute(
        select(AuditLog.server_slug, func.date(AuditLog.ts), AuditLog.outcome, func.count())
        .where(*scope)
        .group_by(AuditLog.server_slug, func.date(AuditLog.ts), AuditLog.outcome)
    )
    for slug, day_val, outcome, n in day_res.all():
        row = per_server.setdefault(slug, {"calls": 0, "errors": 0, "days": {}, "durations": []})
        bucket = row["days"].setdefault(_day_key(day_val), {"calls": 0, "errors": 0})
        bucket["calls"] += int(n)
        if outcome != "success":
            bucket["errors"] += int(n)

    # bounded duration sample per server (newest rows first, same cap semantics)
    dur_res = await db.execute(
        select(AuditLog.server_slug, AuditLog.ts, AuditLog.duration_ms)
        .where(*scope)
        .order_by(AuditLog.ts.desc())
        .limit(DURATION_FETCH_CAP)
    )
    for slug, _ts, duration_ms in dur_res.all():
        per_server.setdefault(slug, {"calls": 0, "errors": 0, "days": {}, "durations": []})["durations"].append(duration_ms)

    rows: list[dict] = []
    total_days = max(1, int((now - start).total_seconds() // 86400))
    for slug, agg in per_server.items():
        durations = sorted(agg["durations"])
        rows.append(
            {
                "server": slug,
                "calls": agg["calls"],
                "errors": agg["errors"],
                "error_rate": round(100.0 * agg["errors"] / agg["calls"], 1) if agg["calls"] else None,
                "p50_ms": _percentile(durations, 0.50),
                "p95_ms": _percentile(durations, 0.95),
                "sparkline": _sparkline_from_days(agg["days"], total_days, now),
            }
        )
    rows.sort(key=lambda r: (-r["calls"], r["server"]))
    return rows


async def _top_tools(db: AsyncSession, scope: list) -> list[dict]:
    """Admin top exposed tools by calls over the window (one group-by, no row
    fetch). Ordered by calls descending, then name; capped at TOP_TOOLS_MAX."""
    res = await db.execute(
        select(AuditLog.tool_exposed_name, AuditLog.outcome, func.count())
        .where(*scope)
        .group_by(AuditLog.tool_exposed_name, AuditLog.outcome)
    )
    tools: dict[str, dict] = {}
    for name, outcome, n in res.all():
        row = tools.setdefault(name, {"tool": name, "calls": 0, "errors": 0})
        row["calls"] += int(n)
        if outcome != "success":
            row["errors"] += int(n)
    rows = sorted(tools.values(), key=lambda r: (-r["calls"], r["tool"]))
    return rows[:TOP_TOOLS_MAX]


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

    # Exact outcome counts (one group-by, no row fetch).
    outcome_res = await db.execute(
        select(AuditLog.outcome, func.count()).where(*scope).group_by(AuditLog.outcome)
    )
    by_outcome: Counter = Counter({o: int(n) for o, n in outcome_res.all()})

    # Exact per-day calls/errors (group by day and outcome, then fold).
    day_res = await db.execute(
        select(func.date(AuditLog.ts), AuditLog.outcome, func.count())
        .where(*scope)
        .group_by(func.date(AuditLog.ts), AuditLog.outcome)
    )
    per_day: dict[str, dict] = {}
    for day_val, outcome, n in day_res.all():
        bucket = per_day.setdefault(_day_key(day_val), {"calls": 0, "errors": 0})
        bucket["calls"] += int(n)
        if outcome != "success":
            bucket["errors"] += int(n)

    # Duration sample for the percentiles: newest rows first, so when the cap
    # ever binds it trims the oldest rows instead of an arbitrary subset.
    dur_res = await db.execute(
        select(AuditLog.ts, AuditLog.duration_ms)
        .where(*scope)
        .order_by(AuditLog.ts.desc())
        .limit(DURATION_FETCH_CAP)
    )
    durations: list[int] = []
    day_durations: dict[str, list[int]] = {}
    for ts, duration_ms in dur_res.all():
        durations.append(duration_ms)
        day_durations.setdefault(ts.date().isoformat(), []).append(duration_ms)

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
    # complete series with no gaps. Calls/errors per day are exact; the per-day
    # p95 comes from the newest-rows duration sample.
    per_day_series: list[dict] = []
    day = (now - window).date()
    while day <= now.date():
        key = day.isoformat()
        counts = per_day.get(key, {"calls": 0, "errors": 0})
        per_day_series.append({
            "date": key,
            "calls": counts["calls"],
            "errors": counts["errors"],
            "p95_ms": _percentile(sorted(day_durations.get(key, [])), 0.95),
        })
        day += timedelta(days=1)

    out = {
        "range": range,
        "window_days": max(1, int(window.total_seconds() // 86400)),
        "audit": {
            "calls": calls,
            "prev_calls": prev_calls,
            "success": by_outcome.get("success", 0),
            "errors": errors,
            "success_rate": success_rate,
            "p50_ms": _percentile(sorted_all, 0.50),
            "p95_ms": _percentile(sorted_all, 0.95),
            "per_day": per_day_series,
        },
    }
    if is_admin:
        out["by_server"] = await _by_server(db, start, now, window)
        out["top_tools"] = await _top_tools(db, scope)
    if not is_admin:
        keys_res = await db.execute(
            select(func.count())
            .select_from(ApiKey)
            .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
        )
        out["own_keys_active"] = int(keys_res.scalar() or 0)
        # All-time, account-scoped counters for the getting-started checklist:
        # onboarding must not un-complete when the chart range changes, so these
        # two COUNTs carry no window filter (unlike the audit aggregates above).
        own_res = await db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.user_id == user.id)
        )
        out["own_calls_total"] = int(own_res.scalar() or 0)
        key_calls_res = await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.user_id == user.id, AuditLog.api_key_id.is_not(None))
        )
        out["own_api_key_calls"] = int(key_calls_res.scalar() or 0)
    return out
