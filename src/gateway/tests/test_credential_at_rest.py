"""Upstream credentials encrypted at rest (Phase 0b verification).

Encryption ALREADY exists (registry/crypto.py, Fernet, key from the
gateway-secrets Secret; LargeBinary column since migration 001, re-encryption on
key rotation by resync_internal_credentials - ADR-026). These tests VERIFY it
end to end instead of re-implementing it:

  1. a credential planted through the REAL admin API is stored as Fernet
     ciphertext (never plaintext bytes) and still decrypts for routing,
  2. the secret appears in NO API response (admin or member) and no audit /
     admin-event row,
  3. the secret is never logged (caplog over the same request flow).

The planted secret is a test-only marker, not a real credential.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from auth.rbac import hash_password
from db.models import Base, Server, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SECRET = " PlaintextMarker sk-test-CRED-LEAK-PROBE-0123456789 "
ADMIN = {"email": "admin-atrest@urumi.local", "password": "admin-atrest-pass-123"}
MEMBER = {"email": "member-atrest@urumi.local", "password": "member-atrest-pass-123"}


@pytest.fixture()
async def harness():
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

    async with SessionLocal() as db:
        db.add_all([
            User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin"),
            User(email=MEMBER["email"], password_hash=await hash_password(MEMBER["password"]), role="member"),
        ])
        await db.commit()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, SessionLocal
    await engine.dispose()


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


@pytest.mark.asyncio
async def test_credential_stored_as_fernet_ciphertext(harness):
    """The DB row holds ciphertext bytes: plaintext absent, decrypt round-trips."""
    client, SessionLocal = harness
    headers = await _login(client, ADMIN["email"], ADMIN["password"])
    r = await client.post(
        "/api/servers",
        json={
            "slug": "cred-probe",
            "url": "http://urumi-demo-time:8000/mcp",
            "auth_type": "bearer",
            "credential": SECRET,
            "timeout_ms": 5000,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    async with SessionLocal() as db:
        srv = (await db.execute(select(Server).where(Server.slug == "cred-probe"))).scalars().one()
        blob = bytes(srv.credential_encrypted or b"")
        assert blob, "credential was not stored at all"
        assert SECRET.encode() not in blob, "PLAINTEXT credential found in the stored bytes"
        assert SECRET.strip().encode() not in blob
        # Fernet tokens are urlsafe-base64 ASCII; a v1 token (version byte 0x80,
        # zero timestamp high bytes) always starts with "gAAAAAB"
        assert blob.startswith(b"gAAAAAB"), f"not a Fernet token (prefix {blob[:8]!r})"
        from registry.crypto import decrypt

        assert decrypt(blob) == SECRET
        assert srv.id == uuid.UUID(sid)


@pytest.mark.asyncio
async def test_secret_absent_from_every_api_response(harness):
    """Admin AND member responses over every server-ish endpoint leak nothing."""
    client, _ = harness
    admin_h = await _login(client, ADMIN["email"], ADMIN["password"])
    r = await client.post(
        "/api/servers",
        json={
            "slug": "cred-probe",
            "url": "http://urumi-demo-time:8000/mcp",
            "auth_type": "header",
            "header_name": "X-Probe",
            "credential": SECRET,
            "timeout_ms": 5000,
        },
        headers=admin_h,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert SECRET not in r.text
    assert created["credential"] == "***"  # masked, never the value

    sid = created["id"]
    # admin reads
    for path in ("/api/servers", f"/api/servers/{sid}", "/api/audit", "/api/admin-events", "/api/tools", "/api/stats"):
        resp = await client.get(path, headers=admin_h)
        assert resp.status_code in (200, 404), f"{path} -> {resp.status_code}"
        assert SECRET not in resp.text, f"LEAK in {path}"
    # member reads (different scope, same secrecy contract)
    member_h = await _login(client, MEMBER["email"], MEMBER["password"])
    for path in ("/api/servers", f"/api/servers/{sid}", "/api/audit", "/api/tools", "/api/stats"):
        resp = await client.get(path, headers=member_h)
        assert resp.status_code in (200, 404), f"{path} -> {resp.status_code}"
        assert SECRET not in resp.text, f"LEAK in {path}"


@pytest.mark.asyncio
async def test_secret_never_logged(harness, caplog):
    """No log record over the whole create/read flow contains the secret."""
    client, _ = harness
    headers = await _login(client, ADMIN["email"], ADMIN["password"])
    r = await client.post(
        "/api/servers",
        json={
            "slug": "cred-probe",
            "url": "http://urumi-demo-time:8000/mcp",
            "auth_type": "bearer",
            "credential": SECRET,
            "timeout_ms": 5000,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    # an update that CHANGES the credential also must not log it
    await client.patch(
        f"/api/servers/{r.json()['id']}",
        json={"credential": SECRET},
        headers=headers,
    )
    await client.get("/api/servers", headers=headers)

    assert SECRET not in caplog.text, "credential LEAKED into logs"
    assert SECRET.strip() not in caplog.text
