"""/api/me feature flags (RC): the dashboard Nav hides Stores / Hosted servers
and their routes show a friendly panel when the Helm flags are off, so /api/me
must expose the settings. Pinned:
  - features.stores mirrors stores_enabled, features.hosted mirrors hosted_enabled
  - the flags follow the settings object (monkeypatching settings flips the payload)
  - the payload still carries user + csrf_token (the original contract)
"""

from __future__ import annotations

import pytest
from config import get_settings
from db.models import Base, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "admin@urumi.local", "password": "admin-pass-123"}


@pytest.fixture()
async def harness(monkeypatch):
    from tests.conftest import sqlite_ready_metadata

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

    from auth.rbac import hash_password

    async with SessionLocal() as db:
        db.add(User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin"))
        await db.commit()

    import httpx

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await engine.dispose()


async def _login(client):
    r = await client.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 200
    return r.cookies


async def test_me_carries_feature_flags_default_off(harness, monkeypatch):
    client = harness
    await _login(client)
    r = await client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "admin"
    assert body["csrf_token"]
    # gateway defaults: both features off (prod shape)
    assert body["features"] == {"stores": False, "hosted": False}


async def test_me_features_follow_settings(harness, monkeypatch):
    client = harness
    await _login(client)
    # pydantic settings are a cached singleton: patch the INSTANCE, not the class
    monkeypatch.setattr(get_settings(), "stores_enabled", True)
    monkeypatch.setattr(get_settings(), "hosted_enabled", True)
    body = (await client.get("/api/me")).json()
    assert body["features"] == {"stores": True, "hosted": True}
    # one flag on, one off
    monkeypatch.setattr(get_settings(), "hosted_enabled", False)
    body = (await client.get("/api/me")).json()
    assert body["features"] == {"stores": True, "hosted": False}
