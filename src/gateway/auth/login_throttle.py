"""Login lockout (hardening, ADR-044; Postgres since Phase 4, ADR-059).

Per-username AND per-client-IP failure counting for the dashboard login. After
`login_lockout_attempts` failed attempts inside `login_lockout_window_seconds`
the key is locked: further attempts get 429 until the window drains (each
failure row ages out independently).

The counters live in the `login_failures` Postgres table, so the lockout is
SHARED across every gateway replica (the in-memory predecessor documented an
attempts x replicas residual - that is gone). Every helper opens its OWN short
DB session and commits independently: a failed login's counter write must
survive the 401 that rolls the request session back.

Nothing here touches the audit trail: routes/users.py records lockouts via
record_admin_event so the trail keeps its transaction semantics.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from config import get_settings

logger = logging.getLogger("gateway.login_throttle")


class ThrottleUnavailable(Exception):
    """The login_failures table is missing (rolled-back/uncommitted migration).

    The lockout control CANNOT work without its counter table, so the login
    endpoint must fail CLOSED for that attempt: an attacker who (somehow) drops
    the table must not get unlimited password guessing, and a rolled-back
    migration must never silently disable the control. The login route maps
    this to 503 with a clear log. Purge/cleanup helpers keep the old fail-open
    policy - losing a cleanup sweep is not a security event.
    """


def _is_missing_table(exc: Exception) -> bool:
    """True when the failure is 'the login_failures table does not exist'."""
    text = str(exc).lower()
    return ("login_failures" in text and "does not exist" in text) or "no such table" in text


def _window_seconds() -> int:
    try:
        value = int(get_settings().login_lockout_window_seconds)
    except (TypeError, ValueError):
        return 300
    return value if value > 0 else 300


def _attempts_allowed() -> int:
    try:
        value = int(get_settings().login_lockout_attempts)
    except (TypeError, ValueError):
        return 5
    return value if value > 0 else 5


async def _count_failures(db, kind: str, key: str) -> int:
    from db.models import LoginFailure
    from sqlalchemy import func, select

    cutoff = datetime.now(UTC) - timedelta(seconds=_window_seconds())
    res = await db.execute(
        select(func.count()).select_from(LoginFailure).where(
            LoginFailure.kind == kind, LoginFailure.key == key, LoginFailure.ts >= cutoff
        )
    )
    return int(res.scalar() or 0)


async def is_locked(db, kind: str, key: str) -> bool:
    """True when this key has reached the failure cap inside the window.

    Missing login_failures table -> ThrottleUnavailable (the login route fails
    CLOSED for that attempt, never silently fail-open - see class docstring).
    Other, transient DB errors keep the ADR-057 fail-open policy: a flaky
    database must not take the login endpoint down or lock honest users out.
    """
    from db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        try:
            return await _count_failures(session, kind, key) >= _attempts_allowed()
        except Exception as exc:
            if _is_missing_table(exc):
                logger.error(
                    "login lockout UNAVAILABLE: the login_failures table is missing "
                    "(rolled-back or uncommitted migration?) - failing CLOSED for this "
                    "login attempt (503). Fix: run migrations to head."
                )
                raise ThrottleUnavailable("login_failures table missing") from exc
            # fail-open: a transiently broken counter must not lock honest users out,
            # and it must not take the login endpoint down (same policy as the /mcp
            # rate limiter - see ADR-057)
            logger.warning("login throttle count failed (allowing attempt): %s", exc)
            return False


async def record_failure(db, kind: str, key: str) -> bool:
    """Record one failure. Returns True when this failure JUST crossed the cap
    (i.e. the row count equals the cap) - the caller audits that transition once.

    Missing login_failures table -> ThrottleUnavailable (fail CLOSED: a failed
    login whose counter cannot be written must not be answered with a retryable
    401, or an attacker could brute-force while the counter is broken)."""
    from db.models import LoginFailure
    from db.session import get_session_factory

    factory = get_session_factory()
    try:
        async with factory() as session:
            session.add(LoginFailure(kind=kind, key=key, ts=datetime.now(UTC)))
            await session.commit()
            count = await _count_failures(session, kind, key)
        return count == _attempts_allowed()
    except Exception as exc:
        if _is_missing_table(exc):
            logger.error(
                "login lockout UNAVAILABLE: cannot record failure - the login_failures "
                "table is missing (rolled-back or uncommitted migration?) - failing "
                "CLOSED for this login attempt (503). Fix: run migrations to head."
            )
            raise ThrottleUnavailable("login_failures table missing") from exc
        logger.warning("login throttle record failed: %s", exc)
        return False


async def record_success(db, kind: str, key: str) -> None:
    """A successful login clears that key's failure rows."""
    from db.models import LoginFailure
    from db.session import get_session_factory
    from sqlalchemy import delete

    factory = get_session_factory()
    try:
        async with factory() as session:
            await session.execute(delete(LoginFailure).where(LoginFailure.kind == kind, LoginFailure.key == key))
            await session.commit()
    except Exception as exc:
        logger.warning("login throttle clear failed: %s", exc)


async def purge_old_failures(keep_seconds: int | None = None) -> None:
    """Sweep expired failure rows (background loop; window doubled for grace)."""
    from db.models import LoginFailure
    from db.session import get_session_factory
    from sqlalchemy import delete

    keep = keep_seconds or (_window_seconds() * 2)
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(delete(LoginFailure).where(LoginFailure.ts < datetime.now(UTC) - timedelta(seconds=keep)))
            await session.commit()
    except Exception as exc:
        logger.warning("login throttle purge failed: %s", exc)
