"""FIX PASS F1-6: GET /api/notifications scoping and secrecy.

Admin: unreachable servers, recent failed tool calls (24h), permission
denials, admin events (revoked keys, disabled servers). Member: only their OWN
failed or denied calls and their own keys expiring within 7 days. The response
never contains key material, argument values or another user's items, and is
capped at 20 items.

Runs against the REAL app, the REAL session-cookie + CSRF auth chain and a
REAL database (embedded sqlite), mirroring test_stats_scoping.py.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from auth.rbac import hash_password
from db.models import AdminEvent, ApiKey, AuditLog, Base, Server, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "admin-notif@urumi.local", "password": "admin-notif-pass-123"}
MEMBER = {"email": "member-notif@urumi.local", "password": "member-notif-pass-123"}
MEMBER2 = {"email": "member2-notif@urumi.local", "password": "member2-notif-pass-123"}

# a planted raw-key-looking string: it must NEVER appear in any response
RAW_KEY = "urumi_sk_PLANTEDRAWKEY_never_show_me_000000000000"


@pytest.fixture()
async def harness():
    """Real app + real sqlite DB with users, an unreachable server, audit rows,
    an expiring member key and a revoked-key admin event."""
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

    now = datetime.now(UTC)
    async with SessionLocal() as db:
        admin = User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin")
        member = User(email=MEMBER["email"], password_hash=await hash_password(MEMBER["password"]), role="member")
        member2 = User(email=MEMBER2["email"], password_hash=await hash_password(MEMBER2["password"]), role="member")
        db.add_all([admin, member, member2])
        await db.flush()

        # member's own key: expiring in 3 days (inside the 7-day window)
        db.add(ApiKey(user_id=member.id, prefix="urumi_sk_", sha256="a" * 64, last4="9zz1",
                      expires_at=now + timedelta(days=3)))
        # member's key that is fine (30 days out): must NOT notify
        db.add(ApiKey(user_id=member.id, sha256="b" * 64, last4="0002", expires_at=now + timedelta(days=30)))
        # member2's expiring key: member must NEVER see it; the planted raw key
        # string sits in the stored digest field, so any leak shows up in text
        db.add(ApiKey(user_id=member2.id, sha256=RAW_KEY, last4="9999", expires_at=now + timedelta(days=2)))

        db.add(Server(slug="down-srv", url="http://down.invalid:9/mcp", auth_type="none",
                      timeout_ms=5000, status="Unreachable", last_error="connection refused"))

        def row(rid: int, user_id, slug: str, tool: str, outcome: str, minutes_ago: float) -> AuditLog:
            return AuditLog(
                id=rid, ts=now - timedelta(minutes=minutes_ago), user_id=user_id, server_slug=slug,
                tool_exposed_name=tool, tool_upstream_name=tool,
                request_id=uuid.uuid4(), duration_ms=10, outcome=outcome,
            )

        db.add(row(701, admin.id, "woo", "woo__create_product", "upstream_error", 10))
        db.add(row(702, member.id, "woo", "woo__list_orders", "timeout", 20))
        db.add(row(712, member.id, "notes", "notes__delete_note", "permission_denied", 25))
        # member2's failure: member must NOT see it
        db.add(row(703, member2.id, "woo", "woo__delete_product", "upstream_error", 5))
        # an old failure outside the 24h window: excluded everywhere
        db.add(row(704, admin.id, "old", "old__fail", "timeout", 60 * 24 * 3))
        db.add(AdminEvent(ts=now - timedelta(minutes=30), actor_user_id=admin.id, action="key.revoke",
                          target_type="key", target_ref="urumi_sk_...1234", outcome="success", details={}))
        await db.commit()

    yield app
    await engine.dispose()


@contextlib.asynccontextmanager
async def _client(app, email: str, password: str):
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        yield c, {"X-CSRF-Token": r.json()["csrf_token"]}


@pytest.mark.asyncio
async def test_admin_sees_fleet_items(harness):
    app = harness
    async with _client(app, ADMIN["email"], ADMIN["password"]) as (client, headers):
        r = await client.get("/api/notifications", headers=headers)
        assert r.status_code == 200, r.text
        items = r.json()["notifications"]
        kinds = {i["kind"] for i in items}
        assert "server_down" in kinds, f"unreachable server item missing: {items}"
        assert "tool_failed" in kinds, "failed tool call item missing"
        assert "admin_event" in kinds, "admin event item missing"
        titles = [i["title"] for i in items]
        assert any("down-srv is unreachable" in t for t in titles), titles
        assert any("woo__create_product failed on woo" in t for t in titles), titles
        assert any("revoked" in t for t in titles), titles
        # shape: every item carries exactly the agreed fields
        for i in items:
            assert set(i) == {"id", "kind", "severity", "title", "detail", "at", "href"}


@pytest.mark.asyncio
async def test_member_sees_only_own_items(harness):
    app = harness
    async with _client(app, MEMBER["email"], MEMBER["password"]) as (client, headers):
        r = await client.get("/api/notifications", headers=headers)
        assert r.status_code == 200, r.text
        items = r.json()["notifications"]
        kinds = {i["kind"] for i in items}
        assert "tool_failed" in kinds, f"member's own failed call missing: {items}"
        assert "permission_denied" in kinds, "member permission denial missing"
        assert "key_expiring" in kinds, "member's expiring key missing"
        # admin-only kinds never reach a member
        assert "server_down" not in kinds, "member must not see server health items"
        assert "admin_event" not in kinds, "member must not see admin events"
        titles = [i["title"] for i in items]
        # only own failures: member2's woo__delete_product must not appear
        assert not any("woo__delete_product" in t for t in titles), "another user's failed call leaked to member"
        # own items present, incl. the expiring key (prefix...last4 only)
        assert any("urumi_sk_...9zz1" in t for t in titles), f"own expiring key item missing: {titles}"
        assert not any("0002" in t for t in titles), "the far-future key must not notify"


@pytest.mark.asyncio
async def test_no_key_material_in_any_response(harness):
    """No key material anywhere: the planted raw-key-looking digest string must
    never appear, and member2's last4 must not reach member."""
    app = harness
    async with _client(app, ADMIN["email"], ADMIN["password"]) as (admin_client, admin_headers), \
            _client(app, MEMBER["email"], MEMBER["password"]) as (member_client, member_headers):
        ra = await admin_client.get("/api/notifications", headers=admin_headers)
        assert ra.status_code == 200, ra.text
        assert RAW_KEY not in ra.text, "planted key material leaked into the admin payload"

        rm = await member_client.get("/api/notifications", headers=member_headers)
        assert RAW_KEY not in rm.text, "member2's stored key digest leaked into the member payload"
        assert "9999" not in rm.text, "member2's key last4 leaked into the member payload"


@pytest.mark.asyncio
async def test_old_failures_outside_24h_excluded(harness):
    app = harness
    async with _client(app, ADMIN["email"], ADMIN["password"]) as (client, headers):
        r = await client.get("/api/notifications", headers=headers)
        titles = " | ".join(i["title"] for i in r.json()["notifications"])
        assert "old__fail" not in titles, "a 3-day-old failure leaked through the 24h window"


@pytest.mark.asyncio
async def test_notifications_capped_at_20():
    """25 unreachable servers -> exactly 20 items (the cap holds)."""
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
        db.add(User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin"))
        for n in range(25):
            db.add(Server(slug=f"down-{n}", url=f"http://down-{n}.invalid:9/mcp", auth_type="none",
                          timeout_ms=5000, status="Unreachable"))
        await db.commit()

    try:
        async with _client(app, ADMIN["email"], ADMIN["password"]) as (client, headers):
            r = await client.get("/api/notifications", headers=headers)
            items = r.json()["notifications"]
            assert r.status_code == 200, r.text
            assert len(items) == 20, f"expected the 20-item cap, got {len(items)}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_notifications_require_login(harness):
    app = harness
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/notifications")
        assert r.status_code == 401, r.status_code

