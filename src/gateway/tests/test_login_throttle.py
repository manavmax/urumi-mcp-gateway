"""Login lockout (hardening pass, ADR-044) through the REAL router.

The real FastAPI app + real sqlite DB (same harness as the admin-router tests);
only the DB engine is swapped. Pinned:
  - N-1 failures -> 401, the Nth failure -> 401 (and locks), anything after -> 429
    with the generic text (no user-existence leak)
  - a successful login RESETS that user's counter
  - the lockout transition writes exactly ONE `login.lockout` admin event
  - per-key isolation (unit level): failures for one username never lock another
    username or a different IP key (the in-memory counter is per (kind, key))
"""

from __future__ import annotations

import httpx
import pytest
from auth import login_throttle
from auth.rbac import hash_password
from config import get_settings
from db.models import AdminEvent, Base, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

VICTIM = {"email": "victim@urumi.local", "password": "correct-horse-42"}
OTHER = {"email": "other@urumi.local", "password": "other-pass-999"}


@pytest.fixture()
async def throttle_harness():
    from tests.conftest import sqlite_ready_metadata

    login_throttle.reset_all()
    sqlite_ready_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with SessionLocal() as db:
        db.add(User(email=VICTIM["email"], password_hash=await hash_password(VICTIM["password"]), role="member"))
        db.add(User(email=OTHER["email"], password_hash=await hash_password(OTHER["password"]), role="member"))
        await db.commit()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, SessionLocal
    await engine.dispose()
    login_throttle.reset_all()


async def _post_login(client, email, password):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


async def _lockout_events(SessionLocal):
    async with SessionLocal() as db:
        res = await db.execute(select(AdminEvent).where(AdminEvent.action == "login.lockout"))
        return res.scalars().all()


@pytest.mark.asyncio
async def test_lockout_returns_429_after_n_attempts(throttle_harness):
    client, _SessionLocal = throttle_harness
    attempts = get_settings().login_lockout_attempts
    # attempts - 1 failures: 401 each
    for i in range(attempts - 1):
        r = await _post_login(client, VICTIM["email"], "wrong-pass")
        assert r.status_code == 401, f"attempt {i + 1}: {r.status_code}"
    # the Nth failure: still a 401, and it LOCKS
    r = await _post_login(client, VICTIM["email"], "wrong-pass")
    assert r.status_code == 401
    # anything after: 429, generic text - including with the CORRECT password
    r = await _post_login(client, VICTIM["email"], VICTIM["password"])
    assert r.status_code == 429, r.text
    assert r.json()["detail"] == "too many attempts, retry later"


@pytest.mark.asyncio
async def test_success_resets_counter(throttle_harness):
    client, _ = throttle_harness
    for _ in range(2):
        r = await _post_login(client, VICTIM["email"], "wrong-pass")
        assert r.status_code == 401
    r = await _post_login(client, VICTIM["email"], VICTIM["password"])
    assert r.status_code == 200
    # fresh budget: attempts - 1 more failures stay 401
    for i in range(get_settings().login_lockout_attempts - 1):
        r = await _post_login(client, VICTIM["email"], "wrong-pass")
        assert r.status_code == 401, f"post-reset attempt {i + 1}: {r.status_code}"


@pytest.mark.asyncio
async def test_lockout_writes_one_audit_event(throttle_harness):
    client, SessionLocal = throttle_harness
    for _ in range(get_settings().login_lockout_attempts + 2):
        await _post_login(client, VICTIM["email"], "wrong-pass")
    events = await _lockout_events(SessionLocal)
    assert len(events) == 1, f"expected exactly one lockout event, got {len(events)}"
    assert events[0].target_ref == VICTIM["email"]
    assert events[0].details["reason"] == "lockout"
    # the audit row must never contain the attempted password
    assert "wrong-pass" not in str(events[0].details)


@pytest.mark.asyncio
async def test_per_key_isolation_unit_level():
    """Per-username AND per-IP counters are independent keys (unit level - the
    router-level tests share one client IP by construction)."""
    login_throttle.reset_all()
    for _ in range(get_settings().login_lockout_attempts):
        login_throttle.record_failure("user", "a@urumi.local")
    assert login_throttle.is_locked("user", "a@urumi.local")
    assert not login_throttle.is_locked("user", "b@urumi.local"), "another username must stay unlocked"
    assert not login_throttle.is_locked("ip", "203.0.113.9"), "a different IP must stay unlocked"
    login_throttle.record_success("user", "a@urumi.local")
    assert not login_throttle.is_locked("user", "a@urumi.local"), "success must clear the lockout"
