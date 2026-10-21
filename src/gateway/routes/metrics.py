"""Gateway observability endpoints (Phase 1, ADR-056).

1. GET /metrics - Prometheus exposition (prometheus_client). NOT exposed through
   the Ingress: the dashboard host routes only /api, /mcp and / to the gateway,
   so an internet request for /metrics lands on the dashboard SPA and 404s,
   never here. At the pod level the default-deny NetworkPolicy lets only the
   ingress-nginx namespace enter the gateway port, so the endpoint is reachable
   in-cluster only; a future scraper needs its own NetworkPolicy exception.
   Application-level guard: set env METRICS_BEARER to require
   `Authorization: Bearer <token>` on this endpoint (constant-time compare).
   Empty (default) leaves the endpoint unauthenticated but in-cluster-only.

2. GET /api/metrics - Dashboard Metrics page aggregates (admin-only), computed
   from the AUDIT TABLE over the last 24h (no Prometheus server required):
   per server calls, errors, error rate, p50/p95 latency and the top classified
   failure reasons (audit error_code = safe category tokens, never raw
   exception text). Parameterized SQLAlchemy only; no argument values in the
   response.
"""

from __future__ import annotations

import hmac
import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

from auth.rbac import require_admin
from config import get_settings
from db.models import AuditLog
from db.session import get_db
from fastapi import APIRouter, Depends, Request, Response
from gw_mcp.metrics import render
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("gateway.metrics")

router = APIRouter()

METRICS_WINDOW_HOURS = 24
# Percentiles are computed in Python over the newest rows of the window:
# portable across Postgres (prod) and sqlite (tests), bounded by a cap (same
# pattern as routes/stats.py).
DURATION_FETCH_CAP = 50000


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(request: Request):
    settings = get_settings()
    expected = (getattr(settings, "metrics_bearer", "") or "").strip()
    if expected:
        auth = request.headers.get("authorization", "")
        supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        # constant-time comparison: the token guards scrape access
        if not hmac.compare_digest(expected, supplied):
            return Response(status_code=401)
    body, content_type = render()
    return Response(content=body, media_type=content_type)


def _percentile(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        return 0
    idx = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[idx]


@router.get("/api/metrics")
async def audit_metrics(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Dashboard Metrics page aggregates (admin-only), computed from the audit
    table over the last 24h: per server calls, errors, error rate, p50/p95
    latency and the top classified failure reasons (audit error_code - safe
    category tokens, never raw exception text)."""
    now = datetime.now(UTC)
    start = now - timedelta(hours=METRICS_WINDOW_HOURS)
    scope = [AuditLog.ts >= start]

    # exact per-server outcome counts (one group-by)
    outcome_res = await db.execute(
        select(AuditLog.server_slug, AuditLog.outcome, func.count())
        .where(*scope)
        .group_by(AuditLog.server_slug, AuditLog.outcome)
    )
    per_server: dict[str, dict] = {}
    for slug, outcome, n in outcome_res.all():
        row = per_server.setdefault(slug, {"calls": 0, "errors": 0, "reasons": Counter(), "durations": []})
        row["calls"] += int(n)
        if outcome != "success":
            row["errors"] += int(n)

    # exact per-server failure reasons (the classified audit error_code)
    reason_res = await db.execute(
        select(AuditLog.server_slug, AuditLog.error_code, func.count())
        .where(*scope, AuditLog.outcome != "success", AuditLog.error_code.is_not(None))
        .group_by(AuditLog.server_slug, AuditLog.error_code)
    )
    for slug, reason, n in reason_res.all():
        per_server.setdefault(slug, {"calls": 0, "errors": 0, "reasons": Counter(), "durations": []})["reasons"][reason] += int(n)

    # bounded duration sample for percentiles (newest rows first)
    dur_res = await db.execute(
        select(AuditLog.server_slug, AuditLog.duration_ms)
        .where(*scope)
        .order_by(AuditLog.ts.desc())
        .limit(DURATION_FETCH_CAP)
    )
    for slug, duration_ms in dur_res.all():
        per_server.setdefault(slug, {"calls": 0, "errors": 0, "reasons": Counter(), "durations": []})["durations"].append(duration_ms)

    rows: list[dict] = []
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
                "top_failures": [{"reason": r, "count": c} for r, c in agg["reasons"].most_common(5)],
            }
        )
    rows.sort(key=lambda r: (-r["calls"], r["server"]))
    return {"window_hours": METRICS_WINDOW_HOURS, "servers": rows}
