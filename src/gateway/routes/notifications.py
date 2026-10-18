"""Notification bell items: GET /api/notifications (FIX PASS F1-6).

Computed from EXISTING data on every request - no new table, no notification
writer. Admin items: unreachable servers, recent failed tool calls (24h),
permission denials (24h), and admin events that changed fleet state (revoked
keys, disabled servers) from the last 24h. Member items: only their OWN failed
or denied calls and their own keys expiring within 7 days.

Secrecy contract (mirrors /api/alerts and ADR-034): never argument values,
never key material (prefix + last4 only), never another user's data for a
member. Max 20 items, newest first, stable ids for the UI.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from auth.rbac import get_current_user_via_session
from db.models import AdminEvent, ApiKey, AuditLog, Server
from db.session import get_db
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

DAY = timedelta(hours=24)
KEY_EXPIRY_WINDOW = timedelta(days=7)
MAX_ITEMS = 20
MAX_FAILURE_ROWS = 6

HUMAN_OUTCOME = {
    "upstream_error": "upstream error",
    "permission_denied": "permission denied",
    "timeout": "timeout",
    "circuit_open": "circuit open",
    "validation_error": "validation error",
}


def _iso(dt: datetime | None) -> str:
    """ISO timestamp with a UTC fallback for naive sqlite datetimes."""
    if dt is None:
        return ""
    return _aware(dt).isoformat()


def _aware(dt: datetime) -> datetime:
    """sqlite returns naive datetimes; treat them as UTC like everywhere else."""
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _item(kind: str, severity: str, title: str, detail: str, at: datetime | None, href: str, ref: str) -> dict:
    return {
        "id": f"{kind}:{ref}",
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "at": _iso(at),
        "href": href,
    }


async def _admin_items(db: AsyncSession, now: datetime) -> list[dict]:
    day_start = now - DAY
    items: list[dict] = []

    # 1) unreachable servers: the fleet health signal admins must see
    servers = list((await db.execute(select(Server).where(Server.enabled.is_(True)))).scalars().all())
    for s in servers:
        if s.status == "Unreachable":
            items.append(
                _item(
                    "server_down",
                    "critical",
                    f"Server {s.slug} is unreachable",
                    s.last_error or s.last_error_category or "unreachable",
                    s.last_checked_at or s.updated_at,
                    "/servers",
                    s.slug,
                )
            )

    # recent failed tool calls in the last 24h, most recent first. Only the
    # tool name, server slug and outcome category - never argument values.
    failures = list(
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.ts >= day_start, AuditLog.outcome != "success")
                .order_by(AuditLog.ts.desc())
                .limit(MAX_FAILURE_ROWS + 1)
            )
        ).scalars().all()
    )
    for a in failures[:MAX_FAILURE_ROWS]:
        kind = "permission_denied" if a.outcome == "permission_denied" else "tool_failed"
        items.append(
            _item(
                kind,
                "critical" if a.outcome == "permission_denied" else "warning",
                f"{a.tool_exposed_name} failed on {a.server_slug}",
                HUMAN_OUTCOME.get(a.outcome, a.outcome),
                a.ts,
                "/audit",
                f"{a.id}",
            )
        )
    if len(failures) > MAX_FAILURE_ROWS:
        items.append(
            _item(
                "tool_failed_many",
                "warning",
                f"{len(failures) - MAX_FAILURE_ROWS}+ more failed tool calls in the last 24 hours",
                "See the audit trail for the full list",
                now,
                "/audit",
                "many",
            )
        )

    # admin events that changed fleet state (rows are already secrecy-safe
    # per ADR-034: only non-secret refs like slug and prefix...last4)
    events = list(
        (
            await db.execute(
                select(AdminEvent)
                .where(AdminEvent.ts >= day_start, AdminEvent.action.in_(["key.revoke", "server.disable"]))
                .order_by(AdminEvent.ts.desc())
                .limit(MAX_ITEMS)
            )
        ).scalars().all()
    )
    for ev in events:
        title = f"API key {ev.target_ref} was revoked" if ev.action == "key.revoke" else f"Server {ev.target_ref} was disabled"
        items.append(
            _item(
                "admin_event",
                "info",
                title,
                f"action {ev.action}",
                ev.ts,
                "/audit",
                f"ev:{ev.id}",
            )
        )
    return items


async def _member_items(db: AsyncSession, user, now: datetime) -> list[dict]:
    day_start = now - DAY
    items: list[dict] = []

    # the member's OWN failed or denied calls, nobody else's
    failures = list(
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.ts >= day_start, AuditLog.user_id == user.id, AuditLog.outcome != "success")
                .order_by(AuditLog.ts.desc())
                .limit(MAX_FAILURE_ROWS + 1)
            )
        ).scalars().all()
    )
    for a in failures[:MAX_FAILURE_ROWS]:
        denied = a.outcome == "permission_denied"
        items.append(
            _item(
                "permission_denied" if denied else "tool_failed",
                "critical" if denied else "warning",
                f"Your call {a.tool_exposed_name} was {HUMAN_OUTCOME.get(a.outcome, a.outcome)}",
                f"on server {a.server_slug}",
                a.ts,
                "/audit",
                f"{a.id}",
            )
        )

    # this user's own active keys expiring within 7 days
    keys = list(
        (
            await db.execute(
                select(ApiKey)
                .where(
                    ApiKey.user_id == user.id,
                    ApiKey.revoked_at.is_(None),
                    ApiKey.expires_at.is_not(None),
                    ApiKey.expires_at >= now,
                    ApiKey.expires_at <= now + KEY_EXPIRY_WINDOW,
                )
                .order_by(ApiKey.expires_at.asc())
                .limit(MAX_ITEMS)
            )
        ).scalars().all()
    )
    for k in keys:
        remaining = (_aware(k.expires_at) - now).days
        when = "today" if remaining < 1 else f"in {remaining} days"
        items.append(
            _item(
                "key_expiring",
                "warning",
                f"API key {k.prefix}...{k.last4} expires {when}",
                f"expires at {_iso(k.expires_at)}",
                k.expires_at,
                "/members",
                f"key:{k.id}",
            )
        )
    return items


@router.get("")
async def get_notifications(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    now = datetime.now(UTC)
    items = await _admin_items(db, now) if user.role == "admin" else await _member_items(db, user, now)
    items.sort(key=lambda i: i["at"], reverse=True)
    return {"notifications": items[:MAX_ITEMS]}
