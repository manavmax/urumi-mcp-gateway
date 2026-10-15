"""STAGE 1 correction: /api/stats admin vs member scoping, and the admin-only
CSV export contract (401 anonymous, 403 for members, 5000 row cap).

Runs against the REAL app, the REAL session-cookie + CSRF auth chain and a
REAL database (embedded sqlite, real SQLAlchemy sessions); only the engine is
swapped, mirroring test_admin_endpoints_router.py.

Each role logs in on its OWN httpx client: login sets a signed session cookie,
so reusing one client for two users silently overwrites the first session.
"""

from __future__ import annotations

import contextlib
import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from auth.rbac import hash_password
from db.models import ApiKey, AuditLog, Base, Server, Tool, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "admin-stats@urumi.local", "password": "admin-stats-pass-123"}
MEMBER = {"email": "member-stats@urumi.local", "password": "member-stats-pass-123"}

# Seeded inside the default 14d window: 6 admin + 2 member + 1 member2 = 9 total
# (old row at day 40 is outside the window and excluded from stats but present in DB)
SEEDED_CALLS = 9


@pytest.fixture()
async def harness():
    """Real app + real sqlite DB with an admin, a member, a server and seeded audit rows."""
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
        admin = User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin")
        member = User(email=MEMBER["email"], password_hash=await hash_password(MEMBER["password"]), role="member")
        # second member for cross-user isolation test
        member2 = User(email="member2-stats@urumi.local", password_hash=await hash_password("member2-pass-123"), role="member")
        db.add_all([admin, member, member2])
        await db.flush()
        # one active api key for the member (drives the member's own_keys_active)
        member_key = ApiKey(user_id=member.id, sha256="a" * 64, last4="0001")
        db.add(member_key)
        srv = Server(slug="stats-srv", url="http://stats-srv.invalid:8000/mcp", auth_type="none", timeout_ms=5000)
        db.add(srv)
        await db.flush()
        db.add(Tool(server_id=srv.id, upstream_name="ping", exposed_name="t__ping", input_schema={}, description=None))
        now = datetime.now(UTC)
        for i in range(5):
            db.add(AuditLog(id=100 + i, ts=now - timedelta(days=1), user_id=admin.id, server_slug="s1",
                            tool_exposed_name="t__ping", tool_upstream_name="ping",
                            request_id=uuid.uuid4(), duration_ms=100 + i, outcome="success"))
        db.add(AuditLog(id=90, ts=now - timedelta(days=1), user_id=admin.id, server_slug="woo",
                        tool_exposed_name="t__bad", tool_upstream_name="ping", request_id=uuid.uuid4(),
                        duration_ms=5, outcome="upstream_error"))
        # member rows: first with api_key_id (origin = MCP client), second without (origin = dashboard chat)
        db.add(AuditLog(id=20, ts=now - timedelta(days=2), user_id=member.id, server_slug="time",
                        tool_exposed_name="time__now", tool_upstream_name="get_time", api_key_id=member_key.id,
                        request_id=uuid.uuid4(), duration_ms=30, outcome="success"))
        db.add(AuditLog(id=21, ts=now - timedelta(days=3), user_id=member.id, server_slug="time",
                        tool_exposed_name="time__now", tool_upstream_name="get_time", api_key_id=None,
                        request_id=uuid.uuid4(), duration_ms=31, outcome="success"))
        # member2 row (isolated): verify member stats never include it
        db.add(AuditLog(id=50, ts=now - timedelta(days=1), user_id=member2.id, server_slug="time",
                        tool_exposed_name="time__now", tool_upstream_name="get_time", api_key_id=None,
                        request_id=uuid.uuid4(), duration_ms=50, outcome="success"))
        # a row outside every window (40 days back) proves the window filter
        db.add(AuditLog(id=30, ts=now - timedelta(days=40), user_id=admin.id, server_slug="old",
                        tool_exposed_name="t__old", tool_upstream_name="old", request_id=uuid.uuid4(),
                        duration_ms=999, outcome="success"))
        await db.commit()

    yield app, SessionLocal
    await engine.dispose()


@contextlib.asynccontextmanager
async def _role_client(app, email: str, password: str):
    """A logged-in client with its own session cookie and matching CSRF header."""
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        yield client, {"X-CSRF-Token": r.json()["csrf_token"]}


@contextlib.asynccontextmanager
async def _anon_client(app):
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _csv_rows(response: httpx.Response) -> list[list[str]]:
    """Parse a BOM-prefixed CSV body (utf-8-sig strips the Excel BOM for readers)."""
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


@pytest.mark.asyncio
async def test_stats_admin_sees_all_member_sees_own(harness):
    app, _session_factory = harness
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as role_admin, \
            _role_client(app, MEMBER["email"], MEMBER["password"]) as role_member, \
            _role_client(app, "member2-stats@urumi.local", "member2-pass-123") as role_member2:
        admin_client, admin_headers = role_admin
        member_client, member_headers = role_member
        member2_client, member2_headers = role_member2

        ra = await admin_client.get("/api/stats", headers=admin_headers)
        assert ra.status_code == 200, ra.text
        a = ra.json()
        # admin sees all: 5 admin + 1 error + 2 member + 1 member2 = 9
        assert a["audit"]["calls"] == 9, "admin sees every user's calls"
        assert a["users_total"] == 3, "admin payload carries the user count"
        assert "own_keys_active" not in a
        # window filter: the 40-day-old row is excluded; the series covers all 14d buckets
        assert len(a["audit"]["per_day"]) == 15
        # total calls sum of per_day must equal total calls
        assert sum(r["calls"] for r in a["audit"]["per_day"]) == 9

        rm = await member_client.get("/api/stats", headers=member_headers)
        assert rm.status_code == 200
        m = rm.json()
        assert m["audit"]["calls"] == 2, "member sees only their own 2 calls"
        assert m["audit"]["success"] == 2
        assert m["audit"]["errors"] == 0
        assert m["audit"]["success_rate"] == 100.0
        # member per-day sum matches member call count (no other-user data)
        assert sum(r["calls"] for r in m["audit"]["per_day"]) == 2
        # own_api_key_calls: 1 of the 2 rows came from an MCP client (api_key_id set)
        assert m["own_api_key_calls"] == 1
        assert "users_total" not in m, "member payload never carries the user count"
        assert m["own_keys_active"] == 1

        # member2 isolation: member stats must not include member2's row
        rm2 = await member2_client.get("/api/stats", headers=member2_headers)
        assert rm2.status_code == 200
        m2 = rm2.json()
        assert m2["audit"]["calls"] == 1, "member2 sees only their own 1 call"
        assert m2["own_api_key_calls"] == 0, "member2 has no API-key-origin rows"

        # per-day series carries only counts and p95 for both roles
        for row in a["audit"]["per_day"] + m["audit"]["per_day"] + m2["audit"]["per_day"]:
            assert set(row.keys()) == {"date", "calls", "errors", "p95_ms"}


@pytest.mark.asyncio
async def test_stats_range_parameter_and_fallback(harness):
    app, _session_factory = harness
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (client, headers):
        r14 = (await client.get("/api/stats", headers=headers)).json()
        assert r14["window_days"] == 14 and r14["range"] == "14d"
        assert len(r14["audit"]["per_day"]) == 15, "the 14d window fills day buckets including today"

        r7 = (await client.get("/api/stats", headers=headers, params={"range": "week"})).json()
        assert r7["window_days"] == 7
        assert len(r7["audit"]["per_day"]) == 8, "a week window fills day buckets including today"
        assert r7["audit"]["calls"] == 9, "6 admin + 2 member + 1 member2 = 9"

        r1 = (await client.get("/api/stats", headers=headers, params={"range": "day"})).json()
        assert r1["window_days"] == 1 and len(r1["audit"]["per_day"]) == 2

        r30 = (await client.get("/api/stats", headers=headers, params={"range": "month"})).json()
        assert r30["window_days"] == 30 and len(r30["audit"]["per_day"]) == 31

        bad = await client.get("/api/stats", headers=headers, params={"range": "bogus"})
        assert bad.status_code == 200, "an unknown range falls back to the default window"
        assert bad.json()["window_days"] == 14 and len(bad.json()["audit"]["per_day"]) == 15


@pytest.mark.asyncio
async def test_stats_never_leak_secrets(harness):
    app, _session_factory = harness
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (client, headers):
        body = (await client.get("/api/stats", headers=headers)).text
    for forbidden in ("credential", "bearer", "password_hash", "fernet", "urumi_sk_"):
        assert forbidden not in body.lower(), f"{forbidden} must never appear in stats"


@pytest.mark.asyncio
async def test_csv_export_admin_only(harness):
    app, _session_factory = harness
    async with _anon_client(app) as anon:
        r = await anon.get("/api/audit/export")
        assert r.status_code == 401, "anonymous export is unauthenticated"

    async with _role_client(app, MEMBER["email"], MEMBER["password"]) as (client, headers):
        r = await client.get("/api/audit/export", headers=headers)
        assert r.status_code == 403, "member CSV export is forbidden server-side"

    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (client, headers):
        r = await client.get("/api/audit/export", headers=headers)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        rows = _csv_rows(r)
        assert rows[0] == ["ts", "user_email", "server_slug", "tool_exposed_name",
                           "tool_upstream_name", "request_id", "duration_ms", "outcome",
                           "error_code", "client_ip"]
        assert len(rows) - 1 == 10, "admin export: 6 admin + 2 member + 1 member2 + 1 old = 10 (no window filter)"


@pytest.mark.asyncio
async def test_csv_export_row_cap_5000(harness):
    app, session_factory = harness
    now = datetime.now(UTC)
    async with session_factory() as db:
        admin_user_id = (await db.execute(select(User.id).where(User.email == ADMIN["email"]))).scalar_one()
        for i in range(5005):
            db.add(AuditLog(id=10000 + i, ts=now - timedelta(hours=1), user_id=admin_user_id,
                            server_slug="bulk", tool_exposed_name="t__bulk", tool_upstream_name="ping",
                            request_id=uuid.uuid4(), duration_ms=1, outcome="success"))
        await db.commit()
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (client, headers):
        r = await client.get("/api/audit/export", headers=headers)
        assert r.status_code == 200
        rows = _csv_rows(r)
        assert len(rows) - 1 == 5000, "export is hard-capped at 5000 data rows"
