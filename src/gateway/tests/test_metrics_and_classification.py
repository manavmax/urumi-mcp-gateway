"""Phase 1 observability: Prometheus /metrics + classified audit failure reasons.

Pins:
  1. a routed tool call records tool_calls_total{server,tool,outcome} and the
     per-server duration histogram,
  2. the audit error_code carries the SAFE classified reason (connection_refused,
     timeout, protocol_error, ...) instead of a bare outcome,
  3. GET /metrics is in-cluster-only by design (not in the ingress paths is a
     chart contract) and honours the optional METRICS_BEARER guard,
  4. GET /api/metrics (admin-only) aggregates the audit table: per-server
     calls/errors/error rate/p50/p95 and top failure reasons.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import gw_mcp.metrics as gw_metrics
import httpx
import pytest
import routes.mcp as mcp_route
import routes.metrics as metrics_route
from auth.keys import create_api_key
from auth.rbac import hash_password
from db.models import AuditLog, Base, Server, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "admin-metrics@urumi.local", "password": "admin-metrics-pass-123"}


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

    async with SessionLocal() as db:
        admin = User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="admin")
        db.add(admin)
        await db.flush()
        srv = Server(slug="notes", url="http://notes.invalid:8000/mcp", auth_type="none", timeout_ms=5000)
        db.add(srv)
        _row, raw_key = await create_api_key(db, admin.id)
        await db.commit()

    captured: list[dict] = []

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, raw_key, captured, SessionLocal
    await engine.dispose()


async def _post_call(client, key, name, arguments):
    return await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
        headers={"Authorization": f"Bearer {key}"},
    )


def _counter_value(name, **labels) -> float:
    for metric in gw_metrics.TOOL_CALLS.collect():
        for sample in metric.samples:
            if sample.name == name and all(sample.labels.get(k) == v for k, v in labels.items()):
                return sample.value
    return 0.0


@pytest.mark.asyncio
async def test_routed_call_records_prometheus_metrics(harness, monkeypatch):
    client, raw_key, _captured, _db = harness

    async def ok_proxy(server, tool, arguments, timeout_seconds=None):
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    monkeypatch.setattr(mcp_route, "call_tool_routed", ok_proxy)

    before = _counter_value("tool_calls_total", server="notes", tool="notes__list_notes", outcome="success")
    r = await _post_call(client, raw_key, "notes__list_notes", {})
    assert r.status_code == 200
    after = _counter_value("tool_calls_total", server="notes", tool="notes__list_notes", outcome="success")
    assert after == before + 1.0, f"counter moved {before} -> {after}"

    # the duration histogram has a bucket observation for the server
    hist = [s for m in gw_metrics.DURATION.collect() for s in m.samples if s.name == "tool_call_duration_seconds_count" and s.labels.get("server") == "notes"]
    assert hist and hist[0].value >= 1.0


    assert hist and hist[0].value >= 1.0


@pytest.mark.asyncio
async def test_upstream_failure_audits_classified_reason(harness, monkeypatch):
    """A dead upstream must audit error_code=connection_refused (the safe
    classified reason), not a bare 'upstream_error'. The router wraps failures
    in UpstreamCallError carrying the category - raised here exactly as the
    real call_tool_routed produces it."""
    from gw_mcp.router import UpstreamCallError

    client, raw_key, captured, _db = harness

    async def dead_proxy(server, tool, arguments, timeout_seconds=None):
        raise UpstreamCallError("Upstream notes error: connection refused", category="connection_refused")

    monkeypatch.setattr(mcp_route, "call_tool_routed", dead_proxy)

    async def fake_log_audit(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(mcp_route, "log_audit", fake_log_audit)
    r = await _post_call(client, raw_key, "notes__list_notes", {})
    assert r.status_code == 502
    assert captured[-1]["outcome"] == "upstream_error"
    assert captured[-1]["error_code"] == "connection_refused", captured[-1]


@pytest.mark.asyncio
async def test_timeout_audits_timeout_reason(harness, monkeypatch):
    client, raw_key, captured, _db = harness

    async def slow_proxy(server, tool, arguments, timeout_seconds=None):
        raise TimeoutError("Upstream notes timed out")

    monkeypatch.setattr(mcp_route, "call_tool_routed", slow_proxy)

    async def fake_log_audit(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(mcp_route, "log_audit", fake_log_audit)
    r = await _post_call(client, raw_key, "notes__list_notes", {})
    assert r.status_code == 504
    assert captured[-1]["outcome"] == "timeout"
    assert captured[-1]["error_code"] == "timeout"


@pytest.mark.asyncio
async def test_rate_limited_call_increments_metric(harness, monkeypatch):
    client, raw_key, _captured, _db = harness
    # exhaust the in-memory limiter for this key
    monkeypatch.setattr(mcp_route, "_check_rate_limit", lambda _key: False)
    r = await _post_call(client, raw_key, "notes__list_notes", {})
    assert r.status_code == 429
    limited = [s for m in gw_metrics.RATE_LIMITED.collect() for s in m.samples if s.name == "rate_limited_total" and s.labels.get("scope") == "key"]
    assert limited and limited[0].value >= 1.0


@pytest.mark.asyncio
async def test_prometheus_endpoint_bearer_guard(harness, monkeypatch):
    client, _raw_key, _captured, _db = harness

    # no token configured: open in-cluster
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert b"tool_calls_total" in r.content

    monkeypatch.setenv("METRICS_BEARER", "scrape-token-not-a-secret")
    monkeypatch.setattr(metrics_route.get_settings, "__call__", lambda self: type("S", (), {"metrics_bearer": "scrape-token-not-a-secret"})(), raising=False)
    # config.get_settings is cached per-process; patch the module-level lookup
    monkeypatch.setattr(metrics_route, "get_settings", lambda: type("S", (), {"metrics_bearer": "scrape-token-not-a-secret"})())

    r = await client.get("/metrics")
    assert r.status_code == 401
    r = await client.get("/metrics", headers={"Authorization": "Bearer scrape-token-not-a-secret"})
    assert r.status_code == 200
    # a WRONG token must fail
    r = await client.get("/metrics", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_metrics_admin_only(harness):
    """Members get 403 on the audit-aggregation endpoint; anonymous 401."""
    client, _raw_key, _captured, _db = harness
    r = await client.get("/api/metrics")
    assert r.status_code == 401
    # login as admin to prove 200
    r = await client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert r.status_code == 200
    r = await client.get("/api/metrics")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["window_hours"] == 24
    assert isinstance(body["servers"], list)


@pytest.mark.asyncio
async def test_api_metrics_member_403(harness):
    client, _raw_key, _captured, SessionLocal = harness
    async with SessionLocal() as db:
        member = User(email="member-metrics@urumi.local", password_hash=await hash_password("member-metrics-pass-123"), role="member")
        db.add(member)
        await db.commit()
    r = await client.post("/api/auth/login", json={"email": "member-metrics@urumi.local", "password": "member-metrics-pass-123"})
    assert r.status_code == 200
    r = await client.get("/api/metrics")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_api_metrics_aggregation_math(harness):
    """Seeded audit rows produce exact calls/errors/rate/percentiles/reasons."""
    client, _raw_key, _captured, SessionLocal = harness
    now = datetime.now(UTC)
    rows = [
        # notes: 4 calls, 2 failures (connection_refused x2), durations 10/20/30/40ms
        (now - timedelta(minutes=5), "success", None, 10),
        (now - timedelta(minutes=4), "success", None, 20),
        (now - timedelta(minutes=3), "upstream_error", "connection_refused", 30),
        (now - timedelta(minutes=2), "upstream_error", "connection_refused", 40),
        # time: 1 call, 1 timeout at 1000ms (older than 24h -> excluded)
        (now - timedelta(days=2), "timeout", "timeout", 1000),
    ]
    async with SessionLocal() as db:
        for i, (ts, outcome, err, dur) in enumerate(rows):
            db.add(AuditLog(
                id=i + 1, ts=ts, user_id=None, server_slug="notes" if i < 4 else "time",
                tool_exposed_name=f"x__t{i}", tool_upstream_name=f"t{i}",
                request_id=uuid.uuid4(), duration_ms=dur, outcome=outcome, error_code=err,
            ))
        await db.commit()

    r = await client.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert r.status_code == 200
    r = await client.get("/api/metrics")
    body = r.json()
    by_slug = {s["server"]: s for s in body["servers"]}

    notes = by_slug.get("notes")
    assert notes is not None
    assert notes["calls"] == 4
    assert notes["errors"] == 2
    assert notes["error_rate"] == 50.0
    assert notes["p50_ms"] in (10, 20, 30, 40)
    assert notes["p95_ms"] == 40
    assert notes["top_failures"] == [{"reason": "connection_refused", "count": 2}]

    # the 2-day-old time row is outside the 24h window
    assert by_slug.get("time") is None

    # sorted by calls descending
    assert [s["calls"] for s in body["servers"]] == sorted([s["calls"] for s in body["servers"]], reverse=True)
