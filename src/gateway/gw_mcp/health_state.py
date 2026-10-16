"""One place to update a Server's health-tracking columns (observability item 1).

Every health check and every upstream call outcome funnels through these two
functions, so the schema stays consistent: status + safe label + category +
timestamps + latency are written together, and the values are ALWAYS the safe
ones (category token + human label derived from it). No raw exception text ever
reaches these columns.

Docs: docs/11_OBSERVABILITY.md
"""

from __future__ import annotations

from datetime import UTC, datetime

from gw_mcp.categorize import category_label


def _now() -> datetime:
    return datetime.now(UTC)


def record_success(server, latency_ms: int | None = None) -> None:
    """A health check or upstream call succeeded: mark Connected + record timings."""
    now = _now()
    server.status = "Connected"
    server.last_error = None
    server.last_error_category = None
    server.last_checked_at = now
    server.last_ok_at = now
    if latency_ms is not None:
        server.last_latency_ms = latency_ms


def record_failure(server, category: str, latency_ms: int | None = None) -> None:
    """A health check or upstream call failed: mark Unreachable + record the category.

    Only the category token and its safe human label are stored - never the exception
    text (which could embed a URL with credentials, a header or a token).
    """
    now = _now()
    server.status = "Unreachable"
    server.last_error = category_label(category)
    server.last_error_category = category
    server.last_checked_at = now
    if latency_ms is not None:
        server.last_latency_ms = latency_ms
