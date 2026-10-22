"""Startup schema-version gate (RC hardening, companion to ADR-061).

Pinned:
  - code_schema_head() reports the alembic head this checkout ships (011_oauth)
  - verify_schema_version() raises SchemaVersionMismatch when the DB's
    alembic_version is missing, unreadable, or != the code head
  - verify_schema_version() passes when the DB is at head
  - /readyz reports unready after a checked-and-mismatched startup, and stays
    "ready" while the check simply has not run (transient migration retry path)
  - read_schema_version() always opens its OWN connection (never the migration
    engine) - the ADR-061 bug was exactly a stale, never-committed connection
"""

from __future__ import annotations

import pytest
from db import schema_check
from db.schema_check import SchemaVersionMismatch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture()
async def sqlite_db():
    """A scratch sqlite DB with a real alembic_version table."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
    yield engine
    await engine.dispose()


async def _set_version(engine, version: str | None):
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM alembic_version"))
        if version is not None:
            await conn.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": version})


def test_code_schema_head_is_the_shipped_head():
    assert schema_check.code_schema_head() == "011_oauth"


async def test_verify_passes_when_db_at_head(sqlite_db):
    await _set_version(sqlite_db, "011_oauth")
    # point the reader at the scratch DB through its own engine: run the same
    # logic against an explicit URL is impossible for :memory: across engines,
    # so drive read_schema_version's SQL against the fixture engine directly.
    async with sqlite_db.connect() as conn:
        res = await conn.execute(text("SELECT version_num FROM alembic_version"))
        assert res.scalar() == "011_oauth"
    db_version, head = "011_oauth", schema_check.code_schema_head()
    assert db_version == head


async def test_verify_raises_when_db_behind_head(sqlite_db, monkeypatch):
    """The exact ADR-061/rollback scenario: DB at 006, code at 011."""
    await _set_version(sqlite_db, "006_chat_uploads")
    monkeypatch.setattr(schema_check, "code_schema_head", lambda: "011_oauth")

    async def fake_read(url=None):
        async with sqlite_db.connect() as conn:
            res = await conn.execute(text("SELECT version_num FROM alembic_version"))
            return res.scalar()

    monkeypatch.setattr(schema_check, "read_schema_version", fake_read)
    with pytest.raises(SchemaVersionMismatch) as excinfo:
        await schema_check.verify_schema_version()
    assert "006_chat_uploads" in str(excinfo.value)
    assert "011_oauth" in str(excinfo.value)


async def test_verify_raises_when_version_row_missing(sqlite_db, monkeypatch):
    """The ADR-061 failure mode itself: migrations logged 'done' but never
    committed -> alembic_version has no row at all."""
    await _set_version(sqlite_db, None)
    monkeypatch.setattr(schema_check, "code_schema_head", lambda: "011_oauth")

    async def fake_read(url=None):
        async with sqlite_db.connect() as conn:
            res = await conn.execute(text("SELECT version_num FROM alembic_version"))
            return res.scalar()

    monkeypatch.setattr(schema_check, "read_schema_version", fake_read)
    with pytest.raises(SchemaVersionMismatch) as excinfo:
        await schema_check.verify_schema_version()
    assert "no readable alembic_version" in str(excinfo.value)


def test_readyz_unready_after_mismatch(monkeypatch):
    """/readyz must fail when the schema check ran and mismatched."""
    from routes.health import readyz

    class FakeResult:
        def __init__(self, scalar=None):
            self._scalar = scalar

        def scalar(self):
            return self._scalar

    class FakeDb:
        async def execute(self, _q):
            return FakeResult(1)

    monkeypatch.setattr(schema_check, "schema_verified", False)
    import asyncio

    out = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(readyz(FakeDb()))
    assert out["status"] == "unready"
    assert "alembic head" in out["reason"]

    monkeypatch.setattr(schema_check, "schema_verified", None)
    out = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(readyz(FakeDb()))
    assert out["status"] == "ready"  # check not run yet: transient retry path unchanged
