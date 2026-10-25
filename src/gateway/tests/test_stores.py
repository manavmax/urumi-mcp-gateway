"""Stores API + sync (Phase 5, ADR-060) through the REAL router.

The provisioner client is faked (the cluster work is the provisioner's own test
surface); these tests pin the GATEWAY's enforcement:
  - 403 everywhere when stores are disabled (the default; core path unchanged)
  - members: create/list/delete only their own stores, capped at maxPerUser
  - admins: see all, exempt from the per-user cap, bound by the global cap
  - slug rules: derived from the name, reserved names and slug/server collisions
    refused, '--' and the store- prefix refused
  - CSRF enforced on create/delete/retry
  - sync: Provisioning -> Ready registers an INTERNAL upstream with slug == store
    slug (tools <slug>__...); failed carries the safe reason; Deleting + gone
    removes the registration and the row
  - the servers API refuses to DELETE an internal upstream (lifecycle-owned)
"""

from __future__ import annotations

import config
import httpx
import pytest
import stores.client as prov_client
import stores.sync as sync
from auth.rbac import hash_password
from db.models import Base, Server, Store, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "admin-st@urumi.local", "password": "admin-st-pass-123"}
MEMBER = {"email": "member-st@urumi.local", "password": "member-st-pass-123"}
MEMBER2 = {"email": "member2-st@urumi.local", "password": "member2-st-pass-123"}

# the fake provisioner's view of the world: slug -> phase
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

    # the routes and sync import get_settings at CALL time from config, and
    # stores.client binds it at module level: patch both bindings. A REAL
    # Settings instance (stores fields overridden, everything else defaults)
    # keeps rbac/session consumers working.
    from config import Settings

    test_settings = Settings(
        stores_enabled=True,
        provisioner_url="http://fake",
        provisioner_token="test-token",
        stores_base_domain="localhost",
        stores_max_per_user=2,
        stores_global_max=4,
        stores_sync_interval_seconds=5,
    )
    monkeypatch.setattr(config, "get_settings", lambda: test_settings)
    monkeypatch.setattr("stores.client.get_settings", lambda: test_settings)
    # sync_once opens its OWN sessions: point it at the test engine
    monkeypatch.setattr("db.session.get_session_factory", lambda: SessionLocal)

    async def fake_provision(slug):
        PROV_STATE[slug] = {"phase": "provisioning"}
        return None

    async def fake_deprovision(slug):
        PROV_STATE[slug] = {"phase": "deleting"}
        return None

    async def fake_state(slug):
        return PROV_STATE.get(slug)  # None = unknown store

    monkeypatch.setattr(prov_client, "provision_store", fake_provision)
    monkeypatch.setattr(prov_client, "deprovision_store", fake_deprovision)
    monkeypatch.setattr(prov_client, "store_state", fake_state)
    # sync imports the client functions at call time; patch the module lookups
    monkeypatch.setattr("stores.client.provision_store", fake_provision)
    monkeypatch.setattr("stores.client.deprovision_store", fake_deprovision)
    monkeypatch.setattr("stores.client.store_state", fake_state)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with SessionLocal() as db:
        db.add(User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin"))
        db.add(User(email=MEMBER["email"], password_hash=await hash_password(MEMBER["password"]), role="member"))
        db.add(User(email=MEMBER2["email"], password_hash=await hash_password(MEMBER2["password"]), role="member"))
        await db.commit()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, SessionLocal
    await engine.dispose()


async def _login(client, email, password):
    """Per-user headers with an EXPLICIT Cookie: a second login on the same
    client would otherwise replace the jar cookie and desync the first
    session's CSRF pair."""
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    from config import get_settings

    cname = get_settings().session_cookie_name
    value = ""
    for part in r.headers.get("set-cookie", "").split(";"):
        if "=" in part and part.strip().startswith(cname + "="):
            value = part.strip().split("=", 1)[1]
            break
    assert value, "no session cookie in login response"
    return {"X-CSRF-Token": r.json()["csrf_token"], "Cookie": f"{cname}={value}", "Content-Type": "application/json"}


async def _create(client, headers, name):
    return await client.post("/api/stores", json={"display_name": name}, headers=headers)


@pytest.mark.asyncio
async def test_stores_403_when_disabled(harness, monkeypatch):
    """The default state: stores disabled -> every /api/stores route 403s and
    nothing about the core path changes."""
    client, _ = harness
    from config import Settings as _S

    monkeypatch.setattr(config, "get_settings", lambda: _S(stores_enabled=False))
    h = await _login(client, ADMIN["email"], ADMIN["password"])
    r = await client.get("/api/stores", headers=h)
    assert r.status_code == 403
    r = await _create(client, h, "somewhere")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_member_can_create_and_only_sees_own(harness):
    client, _SessionLocal = harness
    m = await _login(client, MEMBER["email"], MEMBER["password"])
    r = await _create(client, m, "Bangalore Branch")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "bangalore-branch"
    assert body["namespace"] == "store-bangalore-branch"
    assert body["status"] == "Provisioning"
    assert body["url"] == "http://bangalore-branch.localhost"

    # member sees only their own
    r = await client.get("/api/stores", headers=m)
    assert [s["slug"] for s in r.json()["stores"]] == ["bangalore-branch"]

    # a different member sees none
    m2 = await _login(client, MEMBER2["email"], MEMBER2["password"])
    r = await client.get("/api/stores", headers=m2)
    assert r.json()["stores"] == []

    # admin sees all with owner attribution
    a = await _login(client, ADMIN["email"], ADMIN["password"])
    r = await client.get("/api/stores", headers=a)
    rows = r.json()["stores"]
    assert len(rows) == 1 and rows[0]["owner_email"] == MEMBER["email"]


@pytest.mark.asyncio
async def test_per_user_cap_and_global_cap(harness):
    client, _ = harness
    m = await _login(client, MEMBER["email"], MEMBER["password"])
    r = await _create(client, m, "Alpha")
    assert r.status_code == 201
    r = await _create(client, m, "Beta")
    assert r.status_code == 201
    # cap: maxPerUser=2
    r = await _create(client, m, "Gamma")
    assert r.status_code == 400
    assert "maximum 2" in r.json()["detail"]

    # a second member still gets one (per-user cap is per user)...
    m2 = await _login(client, MEMBER2["email"], MEMBER2["password"])
    r = await _create(client, m2, "Delta")
    assert r.status_code == 201
    # ... until the GLOBAL cap (4): Alpha, Beta, Delta, Epsilon fit...
    a = await _login(client, ADMIN["email"], ADMIN["password"])
    r = await _create(client, a, "Epsilon")
    assert r.status_code == 201
    # ... and the FIFTH store trips it
    r = await _create(client, a, "Zeta")
    assert r.status_code == 400
    assert "platform store limit" in r.json()["detail"]


@pytest.mark.asyncio
async def test_slug_rules_and_collisions(harness):
    client, _ = harness
    m = await _login(client, MEMBER["email"], MEMBER["password"])
    a = await _login(client, ADMIN["email"], ADMIN["password"])
    # reserved
    r = await _create(client, m, "Woo")
    assert r.status_code == 400 and "reserved" in r.json()["detail"]
    # double hyphen collapses... "a--b" -> the slugify collapses to a-b which is fine;
    # a trailing '---x' style name refuses on the store- prefix only:
    r = await _create(client, m, "store-front")
    assert r.status_code == 400 and "reserved" in r.json()["detail"]
    # duplicate slug
    r = await _create(client, m, "alpha")
    assert r.status_code == 201
    r = await _create(client, a, "Alpha")
    assert r.status_code == 400 and "already exists" in r.json()["detail"]
    # slug colliding with a registered SERVER slug
    async with harness[1]() as db:
        db.add(Server(slug="notesy", url="http://notesy:8000/mcp", auth_type="none", timeout_ms=5000))
        await db.commit()
    r = await _create(client, m, "Notesy")
    assert r.status_code == 400 and "collides" in r.json()["detail"]


@pytest.mark.asyncio
async def test_csrf_enforced(harness):
    client, _ = harness
    await _login(client, MEMBER["email"], MEMBER["password"])  # session exists
    r = await client.post("/api/stores", json={"display_name": "no-csrf"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_sync_ready_registers_internal_upstream_and_delete_removes(harness):
    """The full lifecycle through the sync loop's sync_once()."""
    client, SessionLocal = harness
    m = await _login(client, MEMBER["email"], MEMBER["password"])
    r = await _create(client, m, "alpha")
    sid = r.json()["id"]
    PROV_STATE["alpha"] = {"phase": "ready", "reason": ""}

    await sync.sync_once()
    async with SessionLocal() as db:
        store = (await db.execute(select(Store).where(Store.slug == "alpha"))).scalars().one()
        assert store.status == "Ready"
        assert store.failure_reason is None
        srv = (await db.execute(select(Server).where(Server.slug == "alpha"))).scalars().one()
        assert srv.internal is True
        assert srv.url == "http://alpha-woo-mcp.store-alpha.svc:8000/mcp"
        assert srv.enabled is True

    # tools carry the store slug prefix: the SERVER row's slug drives it
    # (aggregator prefixes upstream tools with the server slug)
    # delete: member deletes their own store
    r = await client.delete(f"/api/stores/{sid}", headers=m)
    assert r.status_code == 200
    PROV_STATE["alpha"] = {"phase": "gone", "reason": ""}
    await sync.sync_once()
    async with SessionLocal() as db:
        assert (await db.execute(select(Store).where(Store.slug == "alpha"))).scalars().first() is None
        assert (await db.execute(select(Server).where(Server.slug == "alpha"))).scalars().first() is None


@pytest.mark.asyncio
async def test_sync_failed_records_reason(harness):
    client, SessionLocal = harness
    m = await _login(client, MEMBER["email"], MEMBER["password"])
    r = await _create(client, m, "beta")
    assert r.status_code == 201
    PROV_STATE["beta"] = {"phase": "failed", "reason": "provisioning timed out after 600s"}
    await sync.sync_once()
    async with SessionLocal() as db:
        store = (await db.execute(select(Store).where(Store.slug == "beta"))).scalars().one()
        assert store.status == "Failed"
        assert "timed out" in store.failure_reason
    # retry re-provisions
    r = await client.post(f"/api/stores/{store.id}/retry", headers=m)
    assert r.status_code == 200
    assert r.json()["status"] == "Provisioning"


@pytest.mark.asyncio
async def test_servers_api_refuses_internal_delete_and_mutation(harness):
    """Internal upstreams are lifecycle-owned: delete refused, mutating PATCH
    refused (enable/disable allowed)."""
    client, SessionLocal = harness
    a = await _login(client, ADMIN["email"], ADMIN["password"])
    async with SessionLocal() as db:
        srv = Server(slug="internalstore", url="http://x:8000/mcp", auth_type="none", timeout_ms=5000, internal=True)
        db.add(srv)
        await db.commit()
        sid = srv.id
    r = await client.delete(f"/api/servers/{sid}", headers=a)
    assert r.status_code == 400 and "belongs to a store" in r.json()["detail"]
    r = await client.patch(f"/api/servers/{sid}", json={"url": "http://evil:8000/mcp"}, headers=a)
    assert r.status_code == 400
    # enable/disable stays allowed
    r = await client.patch(f"/api/servers/{sid}", json={"enabled": False}, headers=a)
    assert r.status_code == 200


# ---- ADR-091: store/hosted upstreams follow the global call timeout ----------

@pytest.mark.asyncio
async def test_store_upstream_resolves_to_the_global_call_timeout(harness):
    """The registered store upstream carries the LEGACY_TIMEOUT_MS sentinel
    (not the old hard 5000), so its call timeout resolves to the global call
    default - a slow WordPress call (create_product) gets the full budget."""
    from types import SimpleNamespace

    from db.models import LEGACY_TIMEOUT_MS
    from gw_mcp.router import effective_call_timeout_seconds

    client, SessionLocal = harness
    m = await _login(client, MEMBER["email"], MEMBER["password"])
    r = await _create(client, m, "alphato")
    assert r.status_code == 201, r.text
    PROV_STATE["alphato"] = {"phase": "ready", "reason": ""}
    await sync.sync_once()
    async with SessionLocal() as db:
        srv = (await db.execute(select(Server).where(Server.slug == "alphato"))).scalars().one()
    assert srv.internal is True
    assert srv.timeout_ms == LEGACY_TIMEOUT_MS
    assert effective_call_timeout_seconds(srv, SimpleNamespace(call_timeout_seconds=15)) == 15.0


@pytest.mark.asyncio
async def test_sync_corrects_a_stale_5000_store_row(harness):
    """A store upstream registered by the pre-ADR-091 sync carries 5000; the
    next sync pass self-heals the sync-owned row to the sentinel."""
    from db.models import LEGACY_TIMEOUT_MS

    client, SessionLocal = harness
    m = await _login(client, MEMBER["email"], MEMBER["password"])
    r = await _create(client, m, "staleto")
    assert r.status_code == 201, r.text
    PROV_STATE["staleto"] = {"phase": "ready", "reason": ""}
    await sync.sync_once()
    async with SessionLocal() as db:
        srv = (await db.execute(select(Server).where(Server.slug == "staleto"))).scalars().one()
        srv.timeout_ms = 5000  # simulate the pre-ADR-091 registration
        await db.commit()
    await sync.sync_once()  # Ready stores are revisited every pass
    async with SessionLocal() as db:
        srv = (await db.execute(select(Server).where(Server.slug == "staleto"))).scalars().one()
        assert srv.timeout_ms == LEGACY_TIMEOUT_MS


@pytest.mark.asyncio
async def test_admin_set_timeout_still_wins_and_list_timeout_unchanged(harness):
    """Sync never rewrites a NON-internal (admin-created) server: an explicit
    7000 survives sync passes and still resolves to 7.0s. The 3s list cut-off
    stays the global list_timeout_seconds setting (the list path never reads
    per-server timeout_ms at all)."""
    from types import SimpleNamespace

    from config import Settings
    from gw_mcp.router import effective_call_timeout_seconds

    client, SessionLocal = harness
    a = await _login(client, ADMIN["email"], ADMIN["password"])
    m = await _login(client, MEMBER["email"], MEMBER["password"])
    r = await client.post(
        "/api/servers",
        json={"slug": "admin-srv", "url": "http://admin-srv.invalid:8000/mcp", "auth_type": "none", "timeout_ms": 7000},
        headers=a,
    )
    assert r.status_code == 201, r.text
    # a live store so the sync pass (transition + Ready self-heal) actually runs
    r = await _create(client, m, "shoply")
    assert r.status_code == 201, r.text
    PROV_STATE["shoply"] = {"phase": "ready", "reason": ""}
    await sync.sync_once()
    await sync.sync_once()
    async with SessionLocal() as db:
        srv = (await db.execute(select(Server).where(Server.slug == "admin-srv"))).scalars().one()
        assert srv.internal is False
        assert srv.timeout_ms == 7000
    assert effective_call_timeout_seconds(srv, SimpleNamespace(call_timeout_seconds=15)) == 7.0
    # the 3s list budget is unchanged by this change (and per-server timeout_ms
    # plays no part in listing: gw_mcp.aggregator uses list_timeout_seconds)
    assert Settings().list_timeout_seconds == 3
    assert Settings().call_timeout_seconds == 15
    # the admin row's id is still valid (nothing was swept away)
    r = await client.get(f"/api/servers/{srv.id}", headers=a)
    assert r.status_code == 200 and r.json()["timeout_ms"] == 7000
