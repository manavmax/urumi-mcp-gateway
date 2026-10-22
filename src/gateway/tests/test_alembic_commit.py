"""alembic commit proof (ADR-061 regression test).

Fails if `alembic upgrade head` does not COMMIT - the exact ADR-061 bug where
alembic logged "Running upgrade ... done" while every migration rolled back at
connection close, leaving no alembic_version row and no schema.

Needs a REAL Postgres (the migrations use pg-only types), provided through
RC_TEST_DATABASE_URL (sqlalchemy async URL, e.g.
postgresql+asyncpg://user:pass@host:5432/rc_alembic_test). Without it the test
SKIPS - printed clearly, not silently.

The proof reads through a SEPARATE connection after the run: a fresh engine,
new transaction, real COMMIT visibility. It also asserts the FIRST migration's
object (users table) exists, not just the version row.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

pytest.importorskip("alembic", reason="alembic ships with the gateway requirements")

GW_ROOT = Path(__file__).resolve().parents[1]


def _test_database_url() -> str | None:
    return os.environ.get("RC_TEST_DATABASE_URL") or None


@pytest.fixture()
async def scratch_db_url():
    url = _test_database_url()
    if not url:
        pytest.skip("RC_TEST_DATABASE_URL not set - alembic commit proof needs a real Postgres")
    url = f"{url}_alembic_{os.getpid()}"
    # create the scratch database through a separate autocommit admin connection

    import asyncpg
    import sqlalchemy

    parent = sqlalchemy.engine.make_url(url.rsplit("/", 1)[0])
    target_db = url.rsplit("/", 1)[1]

    async def admin_exec(statement: str):
        conn = await asyncpg.connect(
            host=parent.host, port=parent.port or 5432, user=parent.username, password=parent.password, database="postgres"
        )
        try:
            await conn.execute(statement)
        finally:
            await conn.close()

    await admin_exec(f'DROP DATABASE IF EXISTS "{target_db}"')
    await admin_exec(f'CREATE DATABASE "{target_db}"')
    yield url
    await admin_exec(f'DROP DATABASE IF EXISTS "{target_db}"')


async def test_alembic_upgrade_head_commits(scratch_db_url):
    """Run alembic upgrade head, then read through a SEPARATE connection:
    alembic_version must be committed at head and 001's users table must exist."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    def run_upgrade():
        cfg = Config(str(GW_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(GW_ROOT / "alembic"))
        cfg.set_main_option("sqlalchemy.url", scratch_db_url)
        command.upgrade(cfg, "head")

    await asyncio.to_thread(run_upgrade)

    # SEPARATE connection: brand-new engine, own transaction (the ADR-061 bug
    # is invisible to the migration connection itself)
    engine = create_async_engine(scratch_db_url)
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            users_exists = (
                await conn.execute(
                    text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='users')")
                )
            ).scalar()
            login_failures_exists = (
                await conn.execute(
                    text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='login_failures')")
                )
            ).scalar()
    finally:
        await engine.dispose()

    from db.schema_check import code_schema_head

    head = code_schema_head()
    assert head is not None
    assert version == head, f"alembic_version is {version!r}, expected committed head {head!r}"
    assert users_exists, "users table (migration 001) does not exist - migrations did not commit"
    assert login_failures_exists, "login_failures (migration 008) does not exist - migrations did not commit"


async def test_alembic_upgrade_head_commits_idempotent(scratch_db_url):
    """A second `upgrade head` (the 2-replica no-op path) keeps the committed
    version unchanged and still readable through a separate connection."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    def upgrade():
        cfg = Config(str(GW_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(GW_ROOT / "alembic"))
        cfg.set_main_option("sqlalchemy.url", scratch_db_url)
        command.upgrade(cfg, "head")

    await asyncio.to_thread(upgrade)
    await asyncio.to_thread(upgrade)  # second replica's no-op run

    engine = create_async_engine(scratch_db_url)
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    finally:
        await engine.dispose()
    from db.schema_check import code_schema_head

    assert version == code_schema_head()
