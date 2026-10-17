"""Append-only admin action trail recorder (docs/DECISIONS.md ADR-034).

The trail answers "who did what to which target, when, and did it work" for
dashboard admin actions. It deliberately does NOT record secrets:

  - server credentials -> only "credential_changed": true / "credential_removed": true
  - API keys           -> only "prefix...last4" plus the owner's user id
  - passwords          -> never (not even a hash)
  - request bodies     -> never; details are small dicts of named non-secret facts
  - login.failed       -> attempted email sanitized: stored only if valid email format,
                          otherwise "invalid_format"; max 254 chars

Write model: record_admin_event() only db.add()s the row into the caller's session,
so the event commits in the SAME transaction as the action it describes - an action
that fails rolls its success event back with it (pinned in tests/test_admin_events.py).
login.failed is the one event that IS its own action; it is written under the existing
in-memory rate-limit pattern (mcp.py _check_rate_limit) and one source (the attempted
email) can write at most LOGIN_FAILED_EVENT_LIMIT rows per LOGIN_FAILED_WINDOW_SECONDS,
so a flood of bad logins cannot flood the table.
"""

from __future__ import annotations

import time
import uuid

from db.models import AdminEvent
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Sizes are bounded here, not by trusting every call site, so one accidental
# free-text detail can never bloat the trail.
MAX_ACTION_LEN = 100
MAX_TARGET_REF_LEN = 320
MAX_DETAIL_LIST = 50
MAX_DETAIL_VALUE_LEN = 200  # max length for any free-text detail value

# login.failed row cap per source (attempted email), 60s sliding window - the same
# shape as the per-key limiter in routes/mcp.py.
LOGIN_FAILED_WINDOW_SECONDS = 60.0
LOGIN_FAILED_EVENT_LIMIT = 10

_login_failed_buckets: dict[str, list[float]] = {}

# Email validation: exactly one @, no whitespace, max 254 chars (RFC 5321)
# We use a simple check rather than a regex because:
# 1. We only need to detect valid-like emails, not verify deliverability
# 2. The regex approach with greedy matching can accept "a@b@c.com" incorrectly
# 3. Checking count('@') == 1 is the simplest correct approach


def _is_valid_email(email: str) -> bool:
    """True if email looks like a valid email address (exactly one @, no whitespace).

    Max 254 chars (RFC 5321). We check count('@') == 1 because a greedy regex
    like ^\\S+@\\S+$ would incorrectly accept "a@b@c.com" (\\S+ matches "b@c.com").
    """
    if not email or len(email) > 254:
        return False
    if email.count("@") != 1:
        return False
    return not any(c.isspace() for c in email)


def sanitize_login_email(email: str) -> str:
    """Sanitize attempted email for login.failed target_ref.

    Returns the email if it looks valid (exactly one @, no whitespace, max 254
    chars), otherwise returns "invalid_format". This prevents XSS via HTML in the
    target_ref field which is rendered unescaped in the dashboard audit UI.
    """
    if _is_valid_email(email):
        return email[:254]
    return "invalid_format"


def record_admin_event(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_ref: str,
    outcome: str = "success",
    details: dict | None = None,
) -> None:
    """Append one event to the caller's session (same transaction as the action).

    Does NOT commit: the route's existing commit (or the get_db dependency's)
    commits action + event together; any failure rolls both back.

    All free-text detail values are capped to MAX_DETAIL_VALUE_LEN (200 chars) to
    prevent bloat from accidental or malicious oversized content.
    """
    safe_details: dict = {}
    if details:
        for k, v in details.items():
            if isinstance(v, str):
                safe_details[k] = v[:MAX_DETAIL_VALUE_LEN]
            else:
                safe_details[k] = v
    db.add(
        AdminEvent(
            actor_user_id=actor_user_id,
            action=action[:MAX_ACTION_LEN],
            target_type=target_type,
            target_ref=target_ref[:MAX_TARGET_REF_LEN],
            outcome=outcome,
            details=safe_details,
        )
    )


def key_ref(prefix: str, last4: str) -> str:
    """The ONLY key material allowed in the trail: prefix + last4, e.g. urumi_sk_...a1b2."""
    return f"{prefix}...{last4}"


def bounded_diff(added: list[str], removed: list[str], *, cap: int = MAX_DETAIL_LIST) -> dict:
    """direction diff for permission.change, list entries capped so a policy
    written with hundreds of rules still produces a SMALL details object."""
    def _cut(names: list[str]) -> tuple[list[str], int]:
        extra = max(0, len(names) - cap)
        return sorted(names)[:cap], extra

    kept_added, extra_added = _cut(added)
    kept_removed, extra_removed = _cut(removed)
    out: dict = {
        "added": kept_added,
        "removed": kept_removed,
        "added_count": len(added),
        "removed_count": len(removed),
    }
    if extra_added:
        out["added_truncated"] = extra_added
    if extra_removed:
        out["removed_truncated"] = extra_removed
    return out


def login_failed_event_allowed(email: str) -> bool:
    """True if this source (attempted email) may write another login.failed row now."""
    now = time.monotonic()
    bucket = [t for t in _login_failed_buckets.get(email, []) if now - t < LOGIN_FAILED_WINDOW_SECONDS]
    if len(bucket) >= LOGIN_FAILED_EVENT_LIMIT:
        _login_failed_buckets[email] = bucket
        return False
    bucket.append(now)
    _login_failed_buckets[email] = bucket
    return True


def reset_login_failed_limiter() -> None:
    """Test hook: cold limiter state, exactly like a restarted gateway."""
    _login_failed_buckets.clear()


async def query_admin_events(
    db,
    *,
    actor_user_id: uuid.UUID | None = None,
    action: str | None = None,
    from_ts=None,
    to_ts=None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AdminEvent], int]:
    """Query helper for GET /api/admin-events (admin-only route enforces the role)."""
    q = select(AdminEvent).order_by(AdminEvent.ts.desc(), AdminEvent.id.desc())
    count_q = select(AdminEvent)
    if actor_user_id:
        q = q.where(AdminEvent.actor_user_id == actor_user_id)
        count_q = count_q.where(AdminEvent.actor_user_id == actor_user_id)
    if action:
        q = q.where(AdminEvent.action == action)
        count_q = count_q.where(AdminEvent.action == action)
    if from_ts is not None:
        q = q.where(AdminEvent.ts >= from_ts)
        count_q = count_q.where(AdminEvent.ts >= from_ts)
    if to_ts is not None:
        q = q.where(AdminEvent.ts <= to_ts)
        count_q = count_q.where(AdminEvent.ts <= to_ts)

    total_res = await db.execute(select(func.count()).select_from(count_q.subquery()))
    total = total_res.scalar() or 0
    q = q.limit(limit).offset(offset)
    res = await db.execute(q)
    rows = list(res.scalars().all())
    return rows, total
