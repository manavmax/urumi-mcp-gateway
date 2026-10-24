"""Phase 6 (ADR-062) hosted-server gateway tests through the REAL router.

The provisioner client is faked (the cluster work is the provisioner's own
surface, tested in test_provisioner_units.py); these tests pin the GATEWAY's
enforcement:
  - 403 everywhere when hosted servers are disabled (default; core path unchanged)
  - admin-only surface (members 403)
  - image rules: tag/digest REQUIRED, :latest refused, registry allowlist
  - name rules: DNS-1123-ish, reserved names refused, slug collisions refused
  - env: values never persisted gateway-side nor echoed (only sorted NAMES)
  - sync: Provisioning -> Ready registers an INTERNAL upstream (slug = name,
    tools <name>__...); Deleting + gone removes it and the row
"""

from __future__ import annotations

import json

import config
import httpx
import pytest
import stores.client as prov_client
import stores.sync as sync
from auth.rbac import hash_password
from db.models import Base, Server, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "admin-h@urumi.local", "password": "admin-h-pass-123"}
MEMBER = {"email": "member-h@urumi.local", "password": "member-h-pass-123"}

IMAGE = "ghcr.io/urumi/demo-mcp-time:0.1.0"

# the fake provisioner's view: name -> phase
PROV_STATE: dict[str, dict] = {}


@pytest.fixture()
async def harness(monkeypatch):
    from tests.conftest import sqlite_ready_metadata

    sqlite_ready_metadata()
    PROV_STATE.clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    from config import Settings

    test_settings = Settings(
        stores_enabled=True,  # the sync loop runs with the stores flag
        hosted_enabled=True,
        provisioner_url="http://fake",
        provisioner_token="test-token",
        # ADR-090: a trailing slash on an entry must behave like the bare prefix
        hosted_registry_allowlist="ghcr.io/urumi/",
        hosted_global_max=3,
    )
    monkeypatch.setattr(config, "get_settings", lambda: test_settings)
    monkeypatch.setattr("stores.client.get_settings", lambda: test_settings)
    monkeypatch.setattr("db.session.get_session_factory", lambda: SessionLocal)

    async def fake_host(name, image, port, env):
        PROV_STATE[name] = {"phase": "provisioning"}
        return None

    async def fake_unhost(name):
        PROV_STATE[name] = {"phase": "deleting"}
        return None

    async def fake_hosted_state(name):
        return PROV_STATE.get(name)

    monkeypatch.setattr(prov_client, "host_server", fake_host)
    monkeypatch.setattr(prov_client, "unhost_server", fake_unhost)
    monkeypatch.setattr(prov_client, "hosted_state", fake_hosted_state)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with SessionLocal() as db:
        db.add(User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin"))
        db.add(User(email=MEMBER["email"], password_hash=await hash_password(MEMBER["password"]), role="member"))
        await db.commit()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, SessionLocal
    await engine.dispose()


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    from config import get_settings

    cname = get_settings().session_cookie_name
    value = ""
    for part in r.headers.get("set-cookie", "").split(";"):
        if "=" in part and part.strip().startswith(cname + "="):
            value = part.strip().split("=", 1)[1]
    return {"Cookie": f"{cname}={value}", "X-CSRF-Token": r.json()["csrf_token"]}


async def test_disabled_flag_403(monkeypatch):
    """Default (hosted off): the API 403s everywhere; the core path unchanged."""
    from tests.conftest import sqlite_ready_metadata

    sqlite_ready_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    from config import Settings as S

    test_settings = S(stores_enabled=True, hosted_enabled=False)
    monkeypatch.setattr(config, "get_settings", lambda: test_settings)
    monkeypatch.setattr("stores.client.get_settings", lambda: test_settings)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    from auth.rbac import hash_password

    async with SessionLocal() as db:
        db.add(User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin"))
        await db.commit()
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
        assert r.status_code == 200
        from config import get_settings

        cname = get_settings().session_cookie_name
        value = ""
        for part in r.headers.get("set-cookie", "").split(";"):
            if "=" in part and part.strip().startswith(cname + "="):
                value = part.strip().split("=", 1)[1]
        h = {"Cookie": f"{cname}={value}"}
        r = await client.get("/api/hosted", headers=h)
        assert r.status_code == 403
        assert "disabled" in r.json()["detail"]
    await engine.dispose()


async def test_create_requires_admin_and_validates(harness):
    client, _ = harness
    admin_h = await _login(client, **ADMIN)
    member_h = await _login(client, **MEMBER)

    r = await client.get("/api/hosted", headers=member_h)
    assert r.status_code == 403
    r = await client.post("/api/hosted", json={"name": "t1", "image": IMAGE, "port": 8000}, headers=member_h)
    assert r.status_code == 403

    # admin create succeeds; env values are NOT in the response
    r = await client.post(
        "/api/hosted",
        json={"name": "time2", "image": IMAGE, "port": 8000, "env": {"SECRET_TOKEN": "super-secret-value"}},
        headers=admin_h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["env_names"] == ["SECRET_TOKEN"]
    assert "super-secret-value" not in json.dumps(body)

    r = await client.get("/api/hosted", headers=admin_h)
    assert r.status_code == 200
    assert "super-secret-value" not in r.text

    # bad images
    for bad in ("demo-mcp-time:0.1.0", "ghcr.io/x", "ghcr.io/x:latest", "docker.io/evil/i:1"):
        r = await client.post("/api/hosted", json={"name": "bad1", "image": bad, "port": 8000}, headers=admin_h)
        assert r.status_code == 400, bad
    # allowlist blocks non-ghcr.io/urumi registries
    r = await client.post("/api/hosted", json={"name": "bad2", "image": "ghcr.io/other/x:1.0", "port": 8000}, headers=admin_h)
    assert r.status_code == 400
    # reserved name
    r = await client.post("/api/hosted", json={"name": "hosted", "image": IMAGE, "port": 8000}, headers=admin_h)
    assert r.status_code == 400
    # duplicate name
    r = await client.post("/api/hosted", json={"name": "time2", "image": IMAGE, "port": 8000}, headers=admin_h)
    assert r.status_code == 400


async def test_sync_registers_and_removes_upstream(harness):
    client, SessionLocal = harness
    admin_h = await _login(client, **ADMIN)

    r = await client.post("/api/hosted", json={"name": "time2", "image": IMAGE, "port": 8000}, headers=admin_h)
    assert r.status_code == 201, r.text
    hosted_id = r.json()["id"]

    # ready: the sync registers an internal upstream (slug = name)
    PROV_STATE["time2"] = {"phase": "ready", "reason": ""}
    await sync.sync_hosted_once()
    async with SessionLocal() as db:
        srv = (await db.execute(select(Server).where(Server.slug == "time2"))).scalars().first()
        assert srv is not None
        assert srv.internal is True
        assert srv.url == "http://time2.hosted-time2.svc:8000/mcp"

    # delete: teardown removes the upstream and the row
    r = await client.delete(f"/api/hosted/{hosted_id}", headers=admin_h)
    assert r.status_code == 200
    PROV_STATE["time2"] = {"phase": "gone"}
    await sync.sync_hosted_once()
    async with SessionLocal() as db:
        assert (await db.execute(select(Server).where(Server.slug == "time2"))).scalars().first() is None
        from db.models import HostedServer

        assert (await db.execute(select(HostedServer).where(HostedServer.name == "time2"))).scalars().first() is None


async def test_provision_timeout_marks_failed(harness):
    client, SessionLocal = harness
    admin_h = await _login(client, **ADMIN)
    r = await client.post("/api/hosted", json={"name": "slow2", "image": IMAGE, "port": 8000}, headers=admin_h)
    assert r.status_code == 201
    # simulate an old row: the budget expired while still provisioning
    from datetime import UTC, datetime, timedelta

    async with SessionLocal() as db:
        from db.models import HostedServer

        row = (await db.execute(select(HostedServer).where(HostedServer.name == "slow2"))).scalars().first()
        row.created_at = datetime.now(UTC) - timedelta(seconds=600)
        await db.commit()
    await sync.sync_hosted_once()
    async with SessionLocal() as db:
        from db.models import HostedServer

        row = (await db.execute(select(HostedServer).where(HostedServer.name == "slow2"))).scalars().first()
        assert row.status == "Failed"
        assert "not ready" in row.failure_reason


# --------------------------------------------------------------------------- allowlist normalisation (ADR-090)

async def test_allowlist_entry_with_and_without_trailing_slash(monkeypatch):
    """An entry written with a trailing slash ("ghcr.io/manavmax/") must accept
    ghcr.io/manavmax/app:1 exactly like the bare prefix, while the "/" boundary
    still keeps ghcr.io/manavmax-evil and other registries out."""
    from types import SimpleNamespace

    from fastapi import HTTPException
    from hosted.routes import _validate_image

    good = "ghcr.io/manavmax/app:1"
    evil = "ghcr.io/manavmax-evil/app:1"
    other = "docker.io/manavmax/app:1"

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(hosted_registry_allowlist="ghcr.io/manavmax/"))
    assert _validate_image(good) == good
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(hosted_registry_allowlist="ghcr.io/manavmax"))
    assert _validate_image(good) == good

    # the "/" boundary is kept: a longer namespace never matches a shorter prefix
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(hosted_registry_allowlist="ghcr.io/manavmax"))
    with pytest.raises(HTTPException, match="allowlist"):
        _validate_image(evil)
    with pytest.raises(HTTPException, match="allowlist"):
        _validate_image(other)

    # empty allowlist keeps today's behaviour: every registry accepted
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(hosted_registry_allowlist=""))
    assert _validate_image(other) == other

    # blank / slash-only entries are ignored, never matched against
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(hosted_registry_allowlist=", / ,,ghcr.io/manavmax"))
    assert _validate_image(good) == good
    with pytest.raises(HTTPException, match="allowlist"):
        _validate_image(evil)


async def test_allowlist_trailing_slash_end_to_end(harness):
    """The whole POST /api/hosted flow accepts an allowed-registry image when
    the configured entry carries a trailing slash (the values-prod.example form)."""
    client, _ = harness
    admin_h = await _login(client, **ADMIN)
    r = await client.post("/api/hosted", json={"name": "slashy", "image": IMAGE, "port": 8000}, headers=admin_h)
    assert r.status_code == 201, r.text
    # other registries stay rejected
    r = await client.post("/api/hosted", json={"name": "bad3", "image": "ghcr.io/manavmax-evil/app:1", "port": 8000}, headers=admin_h)
    assert r.status_code == 400, r.text
