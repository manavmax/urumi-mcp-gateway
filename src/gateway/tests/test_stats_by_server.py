"""Observability item 2: by_server per-server aggregates (admin only).

Admin /api/stats gains by_server (calls, error_rate, p50, p95, sparkline) built
from exact SQL aggregates over the selected range. Members NEVER receive the
by_server key. No secret strings anywhere in the payload.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from auth.rbac import hash_password
from db.models import AuditLog, Base, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from tests.conftest import sqlite_ready_metadata

ADMIN = {"email": "bs-admin@urumi.local", "password": "bs-admin-pass-123"}
MEMBER = {"email": "bs-member@urumi.local", "password": "bs-member-pass-123"}


@pytest.fixture()
async def harness():
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
        db.add(User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin"))
        db.add(User(email=MEMBER["email"], password_hash=await hash_password(MEMBER["password"]), role="member"))
        await db.flush()
        # woo: 8 calls, 2 errors (25.0%), durations 10..80 -> p95 = 80
        for i in range(8):
            db.add(AuditLog(id=800 + i, ts=now - timedelta(days=1), server_slug="woo",
                            tool_exposed_name="woo__a", tool_upstream_name="a",
                            request_id=uuid.uuid4(), duration_ms=10 * (i + 1),
                            outcome="success" if i < 6 else "upstream_error"))
        # time: 2 calls, 0 errors, duration 5
        for i in range(2):
            db.add(AuditLog(id=900 + i, ts=now - timedelta(days=2), server_slug="time",
                            tool_exposed_name="time__now", tool_upstream_name="t",
                            request_id=uuid.uuid4(), duration_ms=5, outcome="success"))
        await db.commit()

    yield app, SessionLocal, now
    await engine.dispose()


@contextlib.asynccontextmanager
async def _role_client(app, email: str, password: str):
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        yield client, {"X-CSRF-Token": r.json()["csrf_token"]}


def _by_slug(by_server: list[dict]) -> dict[str, dict]:
    return {row["server"]: row for row in by_server}


@pytest.mark.asyncio
async def test_admin_gets_by_server_with_correct_aggregates(harness):
    app, _sf, _now = harness
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (client, headers):
        r = await client.get("/api/stats", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        rows = body["by_server"]
        assert len(rows) == 2
        # sorted by calls, descending
        assert rows[0]["server"] == "woo" and rows[1]["server"] == "time"

        woo = rows[0]
        assert woo["calls"] == 8 and woo["errors"] == 2
        assert woo["error_rate"] == 25.0
        durations = sorted([10, 20, 30, 40, 50, 60, 70, 80])
        assert woo["p50_ms"] == durations[round(0.5 * (len(durations) - 1))]
        assert woo["p95_ms"] == durations[min(len(durations) - 1, round(0.95 * (len(durations) - 1)))]
        # sparkline over 14d range: 14 points (capped), sum == calls
        assert len(woo["sparkline"]) == 14
        assert sum(p["calls"] for p in woo["sparkline"]) == 8
        assert sum(p["errors"] for p in woo["sparkline"]) == 2

        tm = rows[1]
        assert tm["calls"] == 2 and tm["errors"] == 0
        assert tm["error_rate"] == 0.0
        assert tm["p95_ms"] == 5
        # per-point keys are safe and exact
        for point in woo["sparkline"] + tm["sparkline"]:
            assert set(point.keys()) == {"date", "calls", "errors"}


@pytest.mark.asyncio
async def test_member_never_receives_by_server(harness):
    app, _sf, _now = harness
    async with _role_client(app, MEMBER["email"], MEMBER["password"]) as (client, headers):
        body = (await client.get("/api/stats", headers=headers)).json()
    assert "by_server" not in body, "members must never receive by_server"
    # and the whole payload carries no per-server rows at all
    assert "server" not in body


@pytest.mark.asyncio
async def test_by_server_sparkline_length_follows_range(harness):
    app, _sf, _now = harness
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (client, headers):
        week = (await client.get("/api/stats", params={"range": "week"}, headers=headers)).json()
        fourteen = (await client.get("/api/stats", params={"range": "14d"}, headers=headers)).json()
        month = (await client.get("/api/stats", params={"range": "month"}, headers=headers)).json()
    for row in week["by_server"]:
        assert len(row["sparkline"]) == 7, "week -> 7-point sparkline"
    for row in fourteen["by_server"]:
        assert len(row["sparkline"]) == 14, "14d -> 14-point sparkline"
    for row in month["by_server"]:
        assert len(row["sparkline"]) == 14, "month capped at 14 points"


@pytest.mark.asyncio
async def test_by_server_carries_no_secrets(harness):
    app, _sf, _now = harness
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (client, headers):
        body = (await client.get("/api/stats", headers=headers)).text.lower()
    for forbidden in ("credential", "bearer", "password", "fernet", "urumi_sk_", "token"):
        assert forbidden not in body, f"{forbidden} must never appear in by_server stats"
