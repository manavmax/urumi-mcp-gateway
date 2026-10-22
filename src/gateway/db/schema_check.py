"""Startup schema-version gate (RC hardening, companion to ADR-061).

After `alembic upgrade head` runs, the gateway reads `alembic_version` through a
SEPARATE connection (a new engine, not the migration connection) and compares it
with the alembic head the CODE was shipped with (derived from the alembic
script directory, not from a hardcoded string). On mismatch:

  - a clear ERROR is logged (observed version, expected head, remediation),
  - /readyz reports unready (readiness must never look healthy again after a
    rolled-back migration), and
  - the process exits non-zero, so a migration-job-shaped runner (or the
    gateway container itself) fails loudly instead of serving.

The ADR-061 lesson is enforced here: the verification reads the DATABASE, not
the migration runner's own success log.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("gateway.schema_check")


class SchemaVersionMismatch(RuntimeError):
    """The database schema version does not match the code's alembic head."""


def code_schema_head() -> str | None:
    """The alembic head THIS code ships with (from the version files on disk)."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        ini = Path(__file__).resolve().parent.parent / "alembic.ini"
        cfg = Config(str(ini))
        script = ScriptDirectory.from_config(cfg)
        return script.get_current_head()
    except Exception as exc:  # pragma: no cover - only when the install is broken
        logger.error("cannot determine code alembic head: %s", exc)
        return None


async def read_schema_version(database_url: str | None = None) -> str | None:
    """Read alembic_version through a brand-new connection (never reuses the
    migration engine, whose transaction state is exactly what ADR-061 broke)."""
    url = database_url
    if not url:
        from config import get_settings

        url = get_settings().database_url
    engine = create_async_engine(url, poolclass=None)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT version_num FROM alembic_version"))
            return res.scalar()
    except Exception as exc:
        logger.error("cannot read alembic_version from the database: %s", exc)
        return None
    finally:
        await engine.dispose()


async def verify_schema_version(database_url: str | None = None) -> tuple[str | None, str | None]:
    """Return (db_version, code_head). Raises SchemaVersionMismatch on mismatch.

    Called from lifespan AFTER migrations. Also usable by a standalone
    migration job: exiting non-zero on raise is the job's own business.
    """
    db_version = await read_schema_version(database_url)
    head = code_schema_head()
    if head is None:
        raise SchemaVersionMismatch("code alembic head undeterminable")
    if db_version is None:
        raise SchemaVersionMismatch(
            f"database has no readable alembic_version (migrations did not commit?) - code head is {head}"
        )
    if db_version != head:
        raise SchemaVersionMismatch(
            f"database schema version {db_version} != code alembic head {head} - refusing to serve. "
            "DB BEHIND code: a migration was rolled back or never committed (fix: run migrations to head). "
            "DB AHEAD of code: the code was rolled back across a migration boundary (fix: restore the "
            "pre-upgrade pg_dump per docs/UPGRADE_ROLLBACK.md, or re-apply the newer release)."
        )
    logger.info("schema version verified: db=%s code=%s (separate connection)", db_version, head)
    return db_version, head


# Tri-state, set by main.lifespan: None = check not run yet (startup in
# progress or migration connection still failing - existing retry behaviour),
# True = verified, False = ran and MISMATCHED (readyz must fail).
schema_verified: bool | None = None
