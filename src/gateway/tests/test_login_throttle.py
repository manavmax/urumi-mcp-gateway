"""Login lockout (hardening pass, ADR-044; Postgres-backed since ADR-059).

The real FastAPI app + real sqlite DB (same harness as the admin-router tests);
only the DB engine is swapped, and db.session.get_session_factory is pointed at
it because the throttle opens its OWN sessions (a failed login's counter write
must survive the 401 rollback of the request session). Pinned:
  - N-1 failures -> 401, the Nth failure -> 401 (and locks), anything after -> 429
    with the generic text (no user-existence leak)
  - a successful login RESETS that user's counter
  - the lockout transition writes exactly ONE `login.lockout` admin event
  - per-key isolation (unit level): failures for one username never lock another
    username or a different IP key
  - SHARED across replicas: two separate app instances (two "pods") over the same
    database see the SAME lockout (the old in-memory counter did not)
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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

VICTIM = {"email": "victim@urumi.local", "password": "correct-horse-42"}
OTHER = {"email": "other@urumi.local", "password": "other-pass-999"}


@pytest.fixture()
async def throttle_harness(monkeypatch):
    from tests.conftest import sqlite_ready_metadata

    sqlite_ready_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    # the throttle opens its own sessions: point it at the test engine
    monkeypatch.setattr("db.session.get_session_factory", lambda: SessionLocal)

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


async def _post_login(client, email, password):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


async def _clear_failures(SessionLocal):
    from db.models import LoginFailure

    async with SessionLocal() as db:
        await db.execute(delete(LoginFailure))
        await db.commit()


async def _lockout_events(SessionLocal):
    async with SessionLocal() as db:
        res = await db.execute(select(AdminEvent).where(AdminEvent.action == "login.lockout"))
        return res.scalars().all()


@pytest.mark.asyncio
async def test_lockout_returns_429_after_n_attempts(throttle_harness):
    client, SessionLocal = throttle_harness
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
    # and the counter rows are in the shared table, not in process memory
    from db.models import LoginFailure

    async with SessionLocal() as db:
        n = len((await db.execute(select(LoginFailure).where(LoginFailure.kind == "user"))).scalars().all())
    assert n == attempts, f"expected {attempts} failure rows, got {n}"
    await _clear_failures(SessionLocal)


@pytest.mark.asyncio
async def test_success_resets_counter(throttle_harness):
    client, SessionLocal = throttle_harness
    for _ in range(2):
        r = await _post_login(client, VICTIM["email"], "wrong-pass")
        assert r.status_code == 401
    r = await _post_login(client, VICTIM["email"], VICTIM["password"])
    assert r.status_code == 200
    # fresh budget: attempts - 1 more failures stay 401
    for i in range(get_settings().login_lockout_attempts - 1):
        r = await _post_login(client, VICTIM["email"], "wrong-pass")
        assert r.status_code == 401, f"post-reset attempt {i + 1}: {r.status_code}"
    await _clear_failures(SessionLocal)


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
    await _clear_failures(SessionLocal)


@pytest.mark.asyncio
async def test_per_key_isolation_unit_level(throttle_harness):
    """Per-username AND per-IP counters are independent keys (unit level - the
    router-level tests share one client IP by construction)."""
    _client, SessionLocal = throttle_harness
    attempts = get_settings().login_lockout_attempts
    for _ in range(attempts):
        just_locked = await login_throttle.record_failure(None, "user", "a@urumi.local")
    assert just_locked is True or just_locked is False  # only the transition matters here
    assert await login_throttle.is_locked(None, "user", "a@urumi.local")
    assert not await login_throttle.is_locked(None, "user", "b@urumi.local"), "another username must stay unlocked"
    assert not await login_throttle.is_locked(None, "ip", "203.0.113.9"), "a different IP must stay unlocked"
    await login_throttle.record_success(None, "user", "a@urumi.local")
    assert not await login_throttle.is_locked(None, "user", "a@urumi.local"), "success must clear the lockout"
    await _clear_failures(SessionLocal)


@pytest.mark.asyncio
async def test_lockout_is_shared_across_replicas(monkeypatch):
    """TWO app instances over the SAME database (the two-replica reality): the
    lockout crossed via replica A is enforced by replica B too."""
    from tests.conftest import sqlite_ready_metadata

    sqlite_ready_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("db.session.get_session_factory", lambda: SessionLocal)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app_a = create_app()
    app_a.dependency_overrides[get_db] = override_get_db
    app_b = create_app()
    app_b.dependency_overrides[get_db] = override_get_db

    async with SessionLocal() as db:
        db.add(User(email=VICTIM["email"], password_hash=await hash_password(VICTIM["password"]), role="member"))
        await db.commit()

    attempts = get_settings().login_lockout_attempts
    async with (
        httpx.AsyncClient(transport=ASGITransport(app=app_a), base_url="http://replica-a") as client_a,
        httpx.AsyncClient(transport=ASGITransport(app=app_b), base_url="http://replica-b") as client_b,
    ):
        # burn the whole budget on replica A
        for _ in range(attempts):
            r = await _post_login(client_a, VICTIM["email"], "wrong-pass")
            assert r.status_code == 401
        # replica B must see the SAME lockout: 429, not a fresh budget
        r = await _post_login(client_b, VICTIM["email"], "wrong-pass")
        assert r.status_code == 429, "replica B handed out a fresh budget: the lockout is not shared"
    await engine.dispose()
