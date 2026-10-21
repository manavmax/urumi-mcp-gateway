"""Observability item 1: error-category mapping, health-tracking fields, check-now.

- classify() maps the six failure shapes to the stable categories (refused, timeout,
  http 500, invalid JSON, auth 401) including a hanging upstream (timeout).
- A server row after a call failure carries the category + a SAFE label, never raw
  exception text (which could embed a URL with credentials).
- /api/servers: admins see health-tracking details; members see status only, and no
  secret string appears in either payload.
- POST /api/servers/{id}/check: admin-only, CSRF-protected, rate limited 1/5s.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import socket
import ssl
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from auth.rbac import hash_password
from db.models import Base, Server, User
from db.session import get_db
from gw_mcp import categorize
from gw_mcp.breaker import breaker
from gw_mcp.categorize import classify
from gw_mcp.health_state import record_failure, record_success
from httpx import ASGITransport
from main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from tests.conftest import FakeDB, make_server

# ---------------------------------------------------------------------------
# 1. category mapping (pure function) - the six required shapes
# ---------------------------------------------------------------------------

def _connect_error(cause: BaseException) -> httpx.ConnectError:
    """Build a real httpx.ConnectError chained to the given cause (as httpx does)."""
    try:
        raise httpx.ConnectError("connect failed")
    except httpx.ConnectError as exc:
        try:
            raise cause from exc
        except BaseException as raised:
            return raised  # httpx.ConnectError with __cause__ = cause


def test_category_connection_refused():
    cause = ConnectionRefusedError(errno.ECONNREFUSED, "connection refused")
    assert classify(_connect_error(cause)) == "connection_refused"


def test_category_timeout():
    assert classify(TimeoutError()) == "timeout"
    assert classify(httpx.ConnectTimeout("timed out")) == "timeout"
    assert classify(httpx.ReadTimeout("read timed out")) == "timeout"


def test_category_http_500():
    resp = httpx.Response(500, request=httpx.Request("POST", "http://upstream/mcp"))
    exc = httpx.HTTPStatusError("server error", request=resp.request, response=resp)
    assert classify(exc) == "http_error:500"


def test_category_invalid_json():
    # ADR-056: an unparseable upstream response is a broken MCP protocol
    # exchange, classified as protocol_error (not the generic invalid_response)
    assert classify(json.JSONDecodeError("Expecting value", "{}", 1)) == "protocol_error"


def test_category_auth_401():
    resp = httpx.Response(401, request=httpx.Request("POST", "http://upstream/mcp"))
    exc = httpx.HTTPStatusError("unauthorized", request=resp.request, response=resp)
    assert classify(exc) == "auth_rejected"


def test_category_dns_failure():
    assert classify(socket.gaierror(-2, "Name or service not known")) == "dns_failure"


def test_category_tls_error():
    assert classify(ssl.SSLError("certificate verify failed")) == "tls_error"


def test_category_unknown_is_other():
    assert classify(RuntimeError("some unexpected thing")) == "other"


def test_category_exception_group_unwraps_connection_refused():
    """The MCP SDK wraps transport failures in an ExceptionGroup; classify must
    flatten it and find the real cause instead of reporting 'other'."""
    cause = ConnectionRefusedError(errno.ECONNREFUSED, "connection refused")
    connect = _connect_error(cause)
    group = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [connect])
    assert classify(group) == "connection_refused"


def test_category_exception_group_unwraps_dns_failure():
    connect = _connect_error(socket.gaierror(-2, "Name or service not known"))
    group = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [connect])
    assert classify(group) == "dns_failure"


def test_category_exception_group_timeout_inside():
    group = ExceptionGroup("task group", [httpx.ConnectTimeout("timed out")])
    assert classify(group) == "timeout"


def test_category_label_strips_http_code_and_is_safe():
    assert categorize.category_label("http_error:502") == "upstream error"
    assert categorize.category_label("connection_refused") == "connection refused"
    assert categorize.category_label("auth_rejected") == "auth rejected"
    assert categorize.category_label(None) is None
    # a label can never be an exception message
    assert "secret" not in (categorize.category_label("other") or "")


# ---------------------------------------------------------------------------
# 2. health-tracking columns are updated on call outcome, safe values only
# ---------------------------------------------------------------------------

async def test_timeout_call_marks_unreachable_with_category(monkeypatch):
    """A hanging upstream times out -> status Unreachable, category timeout, safe label."""
    import gw_mcp.router as router

    srv = make_server(slug="hang", timeout_ms=100)
    monkeypatch.setattr(router, "breaker", breaker)

    async def hanging_proxy(server, tool, arguments, timeout_seconds=None):
        await asyncio.sleep(5)

    monkeypatch.setattr(router, "proxy_call", hanging_proxy)
    with pytest.raises(TimeoutError):
        await router.call_tool_routed(FakeDB([srv]), "hang__now", {})
    assert srv.status == "Unreachable"
    assert srv.last_error_category == "timeout"
    assert srv.last_error == "timeout"
    assert srv.last_checked_at is not None
    assert srv.last_latency_ms is not None


async def test_success_call_marks_connected_with_timings(monkeypatch):
    import gw_mcp.router as router

    srv = make_server(slug="ok", timeout_ms=5000)
    monkeypatch.setattr(router, "breaker", breaker)

    async def ok_proxy(server, tool, arguments, timeout_seconds=None):
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    monkeypatch.setattr(router, "proxy_call", ok_proxy)
    res = await router.call_tool_routed(FakeDB([srv]), "ok__now", {})
    assert res["content"][0]["text"] == "ok"
    assert srv.status == "Connected"
    assert srv.last_error is None and srv.last_error_category is None
    assert srv.last_checked_at is not None and srv.last_ok_at is not None
    assert srv.last_latency_ms is not None


def test_record_failure_stores_only_safe_label():
    srv = make_server(slug="x")
    record_failure(srv, "connection_refused")
    assert srv.last_error == "connection refused"
    assert srv.last_error_category == "connection_refused"
    assert srv.last_ok_at is None


def test_record_success_clears_category():
    srv = make_server(slug="x")
    record_failure(srv, "timeout")
    record_success(srv, latency_ms=41)
    assert srv.status == "Connected"
    assert srv.last_error is None and srv.last_error_category is None
    assert srv.last_latency_ms == 41


# ---------------------------------------------------------------------------
# 3. /api/servers admin vs member + no secrets + check-now rate limit
# ---------------------------------------------------------------------------

ADMIN = {"email": "obs-admin@urumi.local", "password": "obs-admin-pass-123"}
MEMBER = {"email": "obs-member@urumi.local", "password": "obs-member-pass-123"}


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
        db.add(User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin"))
        db.add(User(email=MEMBER["email"], password_hash=await hash_password(MEMBER["password"]), role="member"))
        srv = Server(
            slug="sink",
            url="http://urumi-sink:8000/mcp",
            auth_type="none",
            enabled=True,
            status="Unreachable",
            last_error="connection refused",
            last_error_category="connection_refused",
            last_checked_at=datetime.now(UTC),
            last_ok_at=None,
            last_latency_ms=210,
            timeout_ms=5000,
        )
        db.add(srv)
        await db.commit()

    yield app, SessionLocal
    await engine.dispose()


@contextlib.asynccontextmanager
async def _role_client(app, email: str, password: str):
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        yield client, {"X-CSRF-Token": r.json()["csrf_token"]}


@pytest.mark.asyncio
async def test_servers_payload_admin_sees_health_details_member_status_only(harness):
    app, _sf = harness
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (admin, ah), \
            _role_client(app, MEMBER["email"], MEMBER["password"]) as (member, mh):
        ra = await admin.get("/api/servers", headers=ah)
        assert ra.status_code == 200, ra.text
        srv_a = ra.json()["servers"][0]
        assert srv_a["status"] == "Unreachable"
        assert srv_a["last_error_category"] == "connection_refused"
        assert srv_a["last_checked_at"] is not None
        assert srv_a["last_latency_ms"] == 210
        assert srv_a["credential"] is None

        rm = await member.get("/api/servers", headers=mh)
        assert rm.status_code == 200
        srv_m = rm.json()["servers"][0]
        # members: status only - no category details, no health timings, no last_error;
        # credential stays masked (None), never a value
        for dead in ("last_error_category", "last_checked_at", "last_ok_at", "last_latency_ms", "last_error"):
            assert dead not in srv_m, f"{dead} must not appear for members"
        assert srv_m["credential"] is None, "member payload must mask credentials"


@pytest.mark.asyncio
async def test_servers_payload_never_leaks_secrets(harness):
    app, _sf = harness
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (admin, ah), \
            _role_client(app, MEMBER["email"], MEMBER["password"]) as (member, mh):
        for client, headers in ((admin, ah), (member, mh)):
            payload = (await client.get("/api/servers", headers=headers)).json()["servers"][0]
            # the only credential-shaped field is the masked marker (None or "***")
            assert payload["credential"] in (None, "***"), "credential must be masked"
            body = (await client.get("/api/servers", headers=headers)).text.lower()
            for forbidden in ("bearer ", "password=", "fernet_key", "urumi_sk_", "token=", "secret-token", "api_key="):
                assert forbidden not in body, f"{forbidden} must never appear in /api/servers"


@pytest.mark.asyncio
async def test_check_now_admin_only_and_rate_limited(harness):
    app, sf = harness
    async with sf() as db:
        server_id = (await db.execute(select(Server.id).where(Server.slug == "sink"))).scalar_one()
    sid = str(server_id)

    # member is forbidden
    async with _role_client(app, MEMBER["email"], MEMBER["password"]) as (member, mh):
        r = await member.post(f"/api/servers/{sid}/check", headers=mh)
        assert r.status_code == 403, f"member check now -> {r.status_code}"

    # admin first check ok, immediate second is rate limited (429)
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (admin, ah):
        r1 = await admin.post(f"/api/servers/{sid}/check", headers=ah)
        assert r1.status_code == 200, r1.text
        r2 = await admin.post(f"/api/servers/{sid}/check", headers=ah)
        assert r2.status_code == 429, f"second immediate check -> {r2.status_code}"

    # CSRF is enforced
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (admin2, _):
        r = await admin2.post(f"/api/servers/{sid}/check", headers={})
        assert r.status_code == 403, "check now without CSRF must be rejected"


# ---------------------------------------------------------------------------
# 4. /api/alerts next-best-action banner state (Item 3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alerts_admin_unreachable_member_calm(harness):
    """Unreachable enabled server -> admin alert row; member gets slugs only."""
    app, _sf = harness
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (admin, ah), \
            _role_client(app, MEMBER["email"], MEMBER["password"]) as (member, mh):
        ra = await admin.get("/api/alerts", headers=ah)
        assert ra.status_code == 200, ra.text
        admin_rows = ra.json()["admin"]
        assert len(admin_rows) == 1
        alert = admin_rows[0]
        assert alert["slug"] == "sink" and alert["kind"] == "unreachable"
        assert alert["category"] == "connection_refused"
        assert alert["reason"] == "connection refused"
        assert "credential" not in str(alert).lower()

        rm = await member.get("/api/alerts", headers=mh)
        assert rm.status_code == 200
        member_payload = rm.json()
        assert "admin" not in member_payload, "member must never see the admin rows"
        assert member_payload["member"]["slugs"] == ["sink"]


@pytest.mark.asyncio
async def test_alerts_high_error_rate_rule(harness):
    """Error rate over the last hour > 20% with >= 5 calls triggers the banner."""
    from db.models import AuditLog

    app, sf = harness
    now = datetime.now(UTC)
    async with sf() as db:
        # sink is currently Connected but has a bad last hour: 6 calls, 2 errors (33%)
        srv = (await db.execute(select(Server).where(Server.slug == "sink"))).scalar_one()
        srv.status = "Connected"
        srv.last_error_category = None
        srv.last_error = None
        for i in range(6):
            db.add(AuditLog(id=5000 + i, ts=now - timedelta(minutes=30), server_slug="sink",
                            tool_exposed_name="sink__a", tool_upstream_name="a",
                            request_id=uuid.uuid4(), duration_ms=10,
                            outcome="success" if i < 4 else "upstream_error"))
        await db.commit()
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (admin, ah):
        rows = (await admin.get("/api/alerts", headers=ah)).json()["admin"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "high_error_rate"
    assert rows[0]["reason"].startswith("33.3% error rate")


@pytest.mark.asyncio
async def test_alerts_healthy_is_empty(harness):
    """No alerts when every enabled server is Connected and error rate is low."""
    app, sf = harness
    async with sf() as db:
        srv = (await db.execute(select(Server).where(Server.slug == "sink"))).scalar_one()
        srv.status = "Connected"
        srv.last_error_category = None
        srv.last_error = None
        await db.commit()
    async with _role_client(app, ADMIN["email"], ADMIN["password"]) as (admin, ah), \
            _role_client(app, MEMBER["email"], MEMBER["password"]) as (member, mh):
        assert (await admin.get("/api/alerts", headers=ah)).json()["admin"] == []
        assert (await member.get("/api/alerts", headers=mh)).json()["member"]["slugs"] == []
