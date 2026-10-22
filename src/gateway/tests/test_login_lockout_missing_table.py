"""Login lockout when the login_failures table is MISSING (RC hardening).

Policy pinned here: a missing lockout table must never silently fail open.
  - is_locked / record_failure raise ThrottleUnavailable when the table is
    absent (rolled-back or uncommitted migration)
  - the login endpoint answers 503 (fail CLOSED) - not 401/429 - for BOTH the
    pre-check and the failure-recording path, so brute-forcing against a broken
    counter is impossible
  - transient DB errors keep the ADR-057 fail-open policy (is_locked -> False)
  - cleanup helpers (record_success, purge) stay fail-open: losing a sweep is
    not a security event
"""

from __future__ import annotations

import httpx
import pytest
from auth import login_throttle
from auth.rbac import hash_password
from db.models import Base, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

VICTIM = {"email": "victim@urumi.local", "password": "correct-horse-42"}


@pytest.fixture()
async def missing_table_harness(monkeypatch):
    """Harness whose DB has every table EXCEPT login_failures."""
    from tests.conftest import sqlite_ready_metadata

    sqlite_ready_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        # drop ONLY the lockout table after a full create_all
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("DROP TABLE login_failures"))
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("db.session.get_session_factory", lambda: SessionLocal)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with SessionLocal() as db:
        db.add(User(email=VICTIM["email"], password_hash=await hash_password(VICTIM["password"]), role="member"))
        await db.commit()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, engine
    await engine.dispose()


async def test_missing_table_login_fails_closed_503(missing_table_harness):
    """A login attempt against a missing login_failures table answers 503 -
    a wrong password must NOT get the normal 401 (which would allow unlimited
    uncounted guessing), and even a CORRECT password is refused while the
    security control is broken."""
    client, _engine = missing_table_harness
    r = await client.post("/api/auth/login", json=VICTIM)
    assert r.status_code == 503, r.text
    assert "lockout storage is missing" in r.json()["detail"]
    # wrong password: same 503, never a 401 that lets guessing continue
    r = await client.post("/api/auth/login", json={"email": VICTIM["email"], "password": "wrong-pass-1"})
    assert r.status_code == 503


async def test_is_locked_raises_throttle_unavailable(missing_table_harness):
    _ = missing_table_harness  # installs the missing-table factory via monkeypatch
    with pytest.raises(login_throttle.ThrottleUnavailable):
        await login_throttle.is_locked(None, "user", "victim@urumi.local")


async def test_record_failure_raises_throttle_unavailable(missing_table_harness):
    _ = missing_table_harness  # installs the missing-table factory via monkeypatch
    with pytest.raises(login_throttle.ThrottleUnavailable):
        await login_throttle.record_failure(None, "user", "victim@urumi.local")


async def test_cleanup_helpers_stay_fail_open(missing_table_harness, caplog):
    """record_success/purge_old_failures are cleanup-only: they log but never
    raise (a missing sweep must not break an otherwise working login)."""
    _client, _engine = missing_table_harness
    with caplog.at_level("WARNING"):
        await login_throttle.record_success(None, "user", "victim@urumi.local")
        await login_throttle.purge_old_failures()
    assert any("login throttle clear failed" in rec.message for rec in caplog.records)


async def test_transient_error_still_fails_open(monkeypatch):
    """ADR-057 policy preserved: a TRANSIENT counter failure (table present)
    allows the attempt instead of taking login down."""
    class Boom:
        def __str__(self):
            return "database is locked (transient)"

    async def failing_count(db, kind, key):
        raise Exception(Boom())

    monkeypatch.setattr(login_throttle, "_count_failures", failing_count)
    assert await login_throttle.is_locked(None, "user", "someone") is False
