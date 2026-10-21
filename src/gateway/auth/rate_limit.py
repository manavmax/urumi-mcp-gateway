"""Per-key and per-user rate limits backed by Postgres (Phase 2, ADR-057).

Counters live in the rate_limit_counters table and are consumed with ONE
atomic upsert (INSERT ... ON CONFLICT DO UPDATE count = count + 1 RETURNING
count), so the limit is enforced identically across every gateway replica —
no shared memory, no Redis. The window is the wall-clock minute: retry-after
is simply "seconds until this minute ends".

Scopes:
  key:<api_key_id>  limited by the key's override (api_keys.rate_limit_per_minute)
                   or the gateway default (rate_limit_per_minute)
  user:<user_id>   limited by rate_limit_user_per_minute; EVERY call counts —
                   /mcp calls with an API key AND chat agent tool calls.

Failure semantics: a limiter problem (DB down) must NOT reject honest callers,
so any exception is logged and the call is ALLOWED (fail-open). A broken
counter is an availability bug; a false 429 against a paying caller is worse.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from config import get_settings
from db.models import RateLimitCounter
from sqlalchemy import delete

logger = logging.getLogger("gateway.ratelimit")

WINDOW_SECONDS = 60


def _window_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(second=0, microsecond=0, tzinfo=now.tzinfo or UTC)


def retry_after_seconds(now: datetime | None = None) -> int:
    """Seconds until the current minute window closes (the Retry-After value)."""
    now = now or datetime.now(UTC)
    return max(1, WINDOW_SECONDS - now.second)


def effective_key_limit(key_row) -> int:
    """The key's own override when set, else the configured default."""
    override = getattr(key_row, "rate_limit_per_minute", None)
    if isinstance(override, int) and override > 0:
        return override
    return get_settings().rate_limit_per_minute


async def _consume(db, scope: str, window: datetime) -> int:
    """Atomic upsert: increment the (scope, minute) counter, return the new value."""
    if db.get_bind().dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:
        from sqlalchemy.dialects.postgresql import insert as dialect_insert

    stmt = (
        dialect_insert(RateLimitCounter)
        .values(scope=scope, window_start=window, count=1)
        .on_conflict_do_update(
            index_elements=[RateLimitCounter.scope, RateLimitCounter.window_start],
            set_={"count": RateLimitCounter.count + 1},
        )
        .returning(RateLimitCounter.count)
    )
    return int((await db.execute(stmt)).scalar_one())


async def consume_and_check(
    *,
    user_id,
    api_key_id=None,
    key_limit: int | None = None,
) -> tuple[bool, str, int]:
    """Consume one call against the key and user limits.

    Returns (allowed, reason, retry_after_seconds). reason is "" when allowed,
    else "key" or "user" (which scope tripped). Both counters are always
    consumed — an over-limit key still burns the user's budget for the call
    that was attempted. Uses its OWN short DB session so the limiter never
    interleaves with a request's transaction.
    """
    from db.session import get_session_factory

    settings = get_settings()
    window = _window_start()
    user_scope = f"user:{user_id}"
    try:
        factory = get_session_factory()
        async with factory() as db:
            if api_key_id is not None:
                key_count = await _consume(db, f"key:{api_key_id}", window)
                user_count = await _consume(db, user_scope, window)
            else:
                key_count = None
                user_count = await _consume(db, user_scope, window)
            await db.commit()
    except Exception as exc:
        # fail-open: a broken counter must not take the gateway's calls down
        logger.warning("rate limit counter failed (allowing call): %s", exc)
        return True, "", 0

    if key_count is not None:
        limit = key_limit if isinstance(key_limit, int) and key_limit > 0 else settings.rate_limit_per_minute
        if key_count > limit:
            return False, "key", retry_after_seconds()
    if user_count > settings.rate_limit_user_per_minute:
        return False, "user", retry_after_seconds()
    return True, "", 0


async def purge_old_counters(keep_minutes: int = 5) -> None:
    """Sweep expired windows (called by the background loop in main.py)."""
    from db.session import get_session_factory

    try:
        factory = get_session_factory()
        async with factory() as db:
            cutoff = _window_start() - timedelta(minutes=keep_minutes)
            await db.execute(delete(RateLimitCounter).where(RateLimitCounter.window_start < cutoff))
            await db.commit()
    except Exception as exc:
        logger.warning("rate limit purge failed: %s", exc)
