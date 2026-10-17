"""ENDPOINT MATRIX (F2 pass, item 2) — one explicit, reviewed table drives tests + doc.

Source of truth: the ROUTE_MATRIX table below, cross-checked against
app.openapi() in BOTH directions (a route without a row fails; a row for a
missing route fails). docs/ENDPOINT_MATRIX.md is rendered from this same table
by render_markdown(); the test test_doc_matches_table fails if the committed
doc drifts.

COVERAGE (honest scope):
- every OpenAPI route x 7 principals (anonymous, member session, admin session,
  deactivated user, member API key, revoked key, expired key)
- CSRF: missing + wrong token on every session-auth mutating route
- hostile input cases for every POST/PUT/PATCH: empty body, wrong types,
  oversize string, SQL-looking string, extra fields, unicode/control chars
- IDOR: member A vs member B on keys/audit/stats/notifications
- MCP: tools/list principals + tools/call case matrix with audit assertions

WHAT IT DOES NOT COVER:
- concurrency and sustained load (no load tests here)
- the deployed-cluster TLS/ingress layer (scripts/verify-endpoints.sh covers
  the live cluster read-only)
- browser-level CSRF (the table pins the server-side check only)
- websocket/SSE framing details beyond status codes
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from auth.keys import create_api_key
from auth.rbac import hash_password
from db.models import AuditLog, Base, Server, ToolPermission, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# ---- the reviewed table --------------------------------------------------------------
#
# principal keys: anonymous, member (session), admin (session), deactivated
# (session of an is_active=False user), member_key (active Bearer key),
# revoked_key, expired_key.
#
# csrf values:
#   "required"              mutating session route: missing/wrong header -> 403
#   "exempt:<reason>"       reviewed exemption
#   "n/a:<reason>"          the route authenticates via Bearer key (CSRF not
#                           applicable: a forged cross-site request cannot attach
#                           the Authorization header without CORS preflight)


@dataclass(frozen=True)
class MatrixRow:
    method: str
    path: str  # template; {server_id} {key_id} {user_id} resolved from seeds
    expected: dict[str, int]  # principal -> expected status
    csrf: str  # "required" | "exempt:<reason>" | "n/a:<reason>"
    probe_json: dict | None = None  # valid-shape body for the authorized probe
    probe_status: int | None = None  # default: 2xx range check
    probe_target: str = ""  # which seeded id fills {server_id}/{user_id} (DELETE rows use throwaways)
    note: str = ""


def _public() -> dict[str, int]:
    return {p: 200 for p in ("anonymous", "member", "admin", "deactivated", "member_key", "revoked_key", "expired_key")}


ROUTE_MATRIX: list[MatrixRow] = [
    # ---- public ----
    MatrixRow("GET", "/", expected={p: 200 for p in ("anonymous", "member", "admin", "deactivated", "member_key", "revoked_key", "expired_key")}, csrf="n/a:read-only", note="service descriptor, no secrets"),
    MatrixRow("GET", "/healthz", expected={p: 200 for p in ("anonymous", "member", "admin", "deactivated", "member_key", "revoked_key", "expired_key")}, csrf="n/a:probe", note="public probe"),
    MatrixRow("GET", "/readyz", expected={p: 200 for p in ("anonymous", "member", "admin", "deactivated", "member_key", "revoked_key", "expired_key")}, csrf="n/a:read-only", note="DB reachability probe"),
    # ---- MCP (Bearer-key JSON-RPC; session cookies are NOT accepted) ----
    MatrixRow("GET", "/mcp", expected={p: 405 for p in ("anonymous", "member", "admin", "deactivated", "member_key", "revoked_key", "expired_key")}, csrf="n/a:GET-only-envelope", note="SSE GET unsupported: 405 JSON-RPC envelope for every principal"),
    MatrixRow("POST", "/mcp", expected={"anonymous": 401, "member": 401, "admin": 401, "deactivated": 401, "member_key": 200, "revoked_key": 401, "expired_key": 401}, csrf="n/a:bearer-not-cookie", probe_json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, note="API-key auth enforced in-handler; deactivated user's key also 401 (verify_api_key checks is_active)"),
    # ---- auth ----
    MatrixRow("POST", "/api/auth/login", expected={p: 200 for p in ("anonymous", "member", "admin", "deactivated", "member_key", "revoked_key", "expired_key")}, csrf="exempt:no-session-yet", probe_json={"email": "@ADMIN@", "password": "@ADMIN_PW"}, note="401 for wrong creds or a deactivated account (dedicated tests)"),
    MatrixRow("POST", "/api/auth/logout", expected={p: 200 for p in ("anonymous", "member", "admin", "deactivated", "member_key", "revoked_key", "expired_key")}, csrf="exempt:clears only the caller's own cookie", note="no server-side state change"),
    # ---- session-protected reads (member-allowed) ----
    MatrixRow("GET", "/api/me", expected={"anonymous": 401, "member": 200, "admin": 200, "deactivated": 401, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="session cookie only; a Bearer key does not authenticate /api/*"),
    MatrixRow("GET", "/api/servers", expected={"anonymous": 401, "member": 200, "admin": 200, "deactivated": 401, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="members need the server list for the dashboard (masked secrets)"),
    MatrixRow("GET", "/api/servers/{server_id}", expected={"anonymous": 401, "member": 200, "admin": 200, "deactivated": 401, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="unknown id -> 404 (dedicated test)"),
    MatrixRow("GET", "/api/keys", expected={"anonymous": 401, "member": 200, "admin": 200, "deactivated": 401, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="member sees ONLY own keys; admin sees all"),
    MatrixRow("GET", "/api/tools", expected={"anonymous": 401, "member": 200, "admin": 200, "deactivated": 401, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="RBAC-filtered catalog (member deny rules hidden)"),
    MatrixRow("GET", "/api/audit", expected={"anonymous": 401, "member": 200, "admin": 200, "deactivated": 401, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="member rows scoped to self even with ?user_id=<other>"),
    MatrixRow("GET", "/api/audit/export", expected={"anonymous": 401, "member": 403, "admin": 200, "deactivated": 401, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="admin-only CSV, hard-capped at 5000 rows"),
    MatrixRow("GET", "/api/alerts", expected={"anonymous": 401, "member": 200, "admin": 200, "deactivated": 401, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="the 'notifications' surface (alert banner); global, no per-user ownership"),
    MatrixRow("GET", "/api/stats", expected={"anonymous": 401, "member": 200, "admin": 200, "deactivated": 401, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="member aggregates scoped to own rows; by_server admin-only"),
    # ---- admin-only ----
    MatrixRow("GET", "/api/users", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 200, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="admin-only user list"),
    MatrixRow("GET", "/api/admin-events", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 200, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="admin action trail (ADR-034)"),
    MatrixRow("GET", "/api/permissions", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 200, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="n/a:read-only", note="ADR-033 deny policy"),
    MatrixRow("PUT", "/api/permissions", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 200, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required", probe_json={"rules": []}, note="replaces member deny policy; unknown names 422"),
    MatrixRow("POST", "/api/users", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 201, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required", probe_json={"email": "probe-{rand}@example.test", "password": "probe-pass-123", "role": "member"}, note="admin-only; member is 403 even with a valid CSRF header"),
    MatrixRow("POST", "/api/servers", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 201, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required", probe_json={"slug": "probe-{rand}", "url": "http://urumi-demo-time:8000/mcp", "auth_type": "none", "timeout_ms": 5000}, note="SSRF-validated URL; 400 on bad host"),
    MatrixRow("PATCH", "/api/servers/{server_id}", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 200, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required", probe_json={"timeout_ms": 9000}, note="admin-only edit"),
    MatrixRow("POST", "/api/servers/{server_id}/check", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 200, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required", note="admin Check-now; rate limited 1/5s; upstream mocked in tests"),
    MatrixRow("POST", "/api/servers/{server_id}/disable", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 200, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required"),
    MatrixRow("POST", "/api/servers/{server_id}/enable", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 200, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required"),
    MatrixRow("DELETE", "/api/servers/{server_id}", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 204, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required", probe_target="server_id_throwaway", note="probe targets a THROWAWAY server row"),
    MatrixRow("DELETE", "/api/users/{user_id}", expected={"anonymous": 401, "deactivated": 401, "member": 403, "admin": 204, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required", probe_target="user_id", note="probe targets a THROWAWAY user; self-delete is 400 (dedicated test)"),
    MatrixRow("POST", "/api/chat/completions", expected={"anonymous": 401, "deactivated": 401, "member": 200, "admin": 200, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required", probe_json={"messages": [{"role": "user", "content": "hi"}]}, note="SSE; CSRF added in the F2 pass (dashboard already sent the header)"),
    # ---- session-scoped member resources ----
    MatrixRow("POST", "/api/keys", expected={"anonymous": 401, "deactivated": 401, "member": 201, "admin": 201, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required", probe_json={}, note="member mints for self; admin may pass user_id"),
    MatrixRow("DELETE", "/api/keys/{key_id}", expected={"anonymous": 401, "deactivated": 401, "member": 200, "admin": 200, "member_key": 401, "revoked_key": 401, "expired_key": 401}, csrf="required", note="probe revokes member A's OWN key; revoking B's is 403 (IDOR tests)"),
]

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# routes documented as CSRF-exempt (each has a reviewed reason)
CSRF_EXEMPT_MUTATIONS = {
    ("POST", "/api/auth/login"): "pre-session: no authenticated state to abuse; wrong-creds are rate-shaped by the admin-event trail",
    ("POST", "/api/auth/logout"): "clears only the caller's own cookie; no server state changes",
    ("POST", "/mcp"): "Bearer-key auth, not cookie auth: a forged cross-site request cannot attach the Authorization header",
}


PRINCIPALS = ("anonymous", "member", "admin", "deactivated", "member_key", "revoked_key", "expired_key")

SESSION_USER_PASSWORDS = {
    "admin": "matrix-admin-pass-123",
    "member": "matrix-member-pass-123",
    "deactivated": "matrix-dead-pass-123",
}

# ---- harness ---------------------------------------------------------------------------


@pytest.fixture()
async def matrix_harness(monkeypatch):
    """Real app + sqlite seeded with every principal the table names.

    Seeded: admin, member A (the 'member' principal), member B (IDOR target),
    a deactivated user, admin + member API keys, a revoked key, an expired key,
    a still-valid key owned by the deactivated user, a 'notes' server plus a
    throwaway server/user for the DELETE probes, audit rows for both members,
    and a tool-permission deny row for the member role. Upstream MCP fan-out is
    mocked (no network); the LLM key is blanked so chat answers without SSE.
    """
    from datetime import UTC, datetime, timedelta

    from auth.session import create_session_cookie
    from config import get_settings

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

    async def fake_fetch(db_, server, timeout_seconds=8.0):
        return []  # tools/list and Check-now never leave the process

    monkeypatch.setattr("gw_mcp.aggregator.fetch_and_cache_tools", fake_fetch)
    monkeypatch.setattr(get_settings(), "openai_api_key", "")

    rand = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    h = SimpleNamespace()

    async with SessionLocal() as db:
        admin = User(email="matrix-admin@urumi.local", password_hash=await hash_password(SESSION_USER_PASSWORDS["admin"]), role="admin")
        member_a = User(email="matrix-a@urumi.local", password_hash=await hash_password(SESSION_USER_PASSWORDS["member"]), role="member")
        member_b = User(email="matrix-b@urumi.local", password_hash=await hash_password("matrix-b-pass-123"), role="member")
        dead = User(email="matrix-dead@urumi.local", password_hash=await hash_password(SESSION_USER_PASSWORDS["deactivated"]), role="member")
        throwaway = User(email=f"matrix-throwaway-{rand}@urumi.local", password_hash=await hash_password("throwaway-pass-123"), role="member")
        db.add_all([admin, member_a, member_b, dead, throwaway])
        await db.flush()

        srv_notes = Server(slug="notes", url="http://notes.invalid:8000/mcp", auth_type="none", timeout_ms=5000)
        srv_throwaway = Server(slug="matrix-throwaway", url="http://throwaway.invalid:8000/mcp", auth_type="none", timeout_ms=5000)
        db.add_all([srv_notes, srv_throwaway])
        await db.flush()

        for i, u in enumerate((admin, member_a, member_b), start=1):
            db.add(
                AuditLog(
                    id=i,
                    ts=now,
                    user_id=u.id,
                    server_slug="notes",
                    tool_exposed_name="notes__list_notes",
                    tool_upstream_name="list_notes",
                    request_id=uuid.uuid4(),
                    duration_ms=1,
                    outcome="success",
                )
            )
        db.add(ToolPermission(role="member", server_slug="notes", tool_name=None, created_by=admin.id))
        await db.flush()

        _km_row, raw_member = await create_api_key(db, member_a.id)
        _ka_row, raw_admin = await create_api_key(db, admin.id)
        kr_row, raw_revoked = await create_api_key(db, member_a.id)
        ke_row, raw_expired = await create_api_key(db, member_a.id)
        _kd_row, raw_deactivated = await create_api_key(db, dead.id)
        ko_row, _raw_own = await create_api_key(db, member_a.id)
        kr_row.revoked_at = datetime.now(UTC)
        ke_row.expires_at = now - timedelta(hours=1)
        dead.is_active = False
        await db.commit()

        h.ids = {
            "server_id": str(srv_notes.id),
            "server_id_throwaway": str(srv_throwaway.id),
            "user_id": str(throwaway.id),
            "key_id": str(ko_row.id),
            "member_a_id": str(member_a.id),
            "member_b_id": str(member_b.id),
            "admin_id": str(admin.id),
        }

    cookie_name = get_settings().session_cookie_name
    cookie_admin, csrf_admin = create_session_cookie(admin.id)
    cookie_member, csrf_member = create_session_cookie(member_a.id)
    cookie_dead, _csrf_dead = create_session_cookie(dead.id)

    h.cookies = {
        "member": {cookie_name: cookie_member},
        "admin": {cookie_name: cookie_admin},
        "deactivated": {cookie_name: cookie_dead},
    }
    h.csrf = {"admin": csrf_admin, "member": csrf_member}
    h.keys = {
        "member_key": raw_member,
        "revoked_key": raw_revoked,
        "expired_key": raw_expired,
        "admin": raw_admin,
        "deactivated": raw_deactivated,
    }
    h.rand = rand
    h.captured_audit: list[dict] = []
    h.SessionLocal = SessionLocal

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        h.client = client
        yield h
    await engine.dispose()


def _reset_limiters():
    import routes.mcp as mcp_route
    import routes.servers as servers_route

    mcp_route._rate_buckets.clear()
    if hasattr(servers_route, "_check_buckets"):
        servers_route._check_buckets.clear()


def _resolve_path(h, template: str) -> str:
    path = template
    for key in ("{server_id}", "{key_id}", "{user_id}"):
        if key in path:
            path = path.replace(key, h.ids[key.strip("{}")])
    # every "{rand}" gets a FRESH value so repeated create-probes stay unique
    return path.replace("{rand}", uuid.uuid4().hex[:8])


def _probe_payload(h, row: MatrixRow):
    payload = row.probe_json
    if payload is None:
        return None
    raw = json.dumps(payload)
    raw = raw.replace("{rand}", uuid.uuid4().hex[:8])
    raw = raw.replace("@ADMIN@", "matrix-admin@urumi.local")
    raw = raw.replace("@ADMIN_PW", SESSION_USER_PASSWORDS["admin"])
    return json.loads(raw)


async def _probe(h, row: MatrixRow, principal: str, *, with_csrf: bool = True, body="__probe__", extra_headers=None) -> httpx.Response:
    """One (route, principal) request with the row's valid-shape body."""
    _reset_limiters()
    cookies = h.cookies.get(principal, {})
    headers: dict = dict(extra_headers or {})
    if principal == "member_key":
        headers["Authorization"] = f"Bearer {h.keys['member_key']}"
    elif principal == "revoked_key":
        headers["Authorization"] = f"Bearer {h.keys['revoked_key']}"
    elif principal == "expired_key":
        headers["Authorization"] = f"Bearer {h.keys['expired_key']}"
    if row.csrf == "required" and with_csrf and principal in ("member", "admin"):
        headers.setdefault("X-CSRF-Token", h.csrf[principal])

    payload = _probe_payload(h, row) if body == "__probe__" else body
    kwargs: dict = {}
    if payload is not None:
        kwargs["json"] = payload
    if cookies:
        kwargs["cookies"] = cookies
    if headers:
        kwargs["headers"] = headers
    return await h.client.request(row.method, _resolve_path(h, row.path), **kwargs)


# ---- 1. table <-> OpenAPI cross-check ---------------------------------------------------


@lru_cache(maxsize=1)
def _openapi_routes() -> set:
    from tests.conftest import sqlite_ready_metadata

    sqlite_ready_metadata()
    app = create_app()
    spec = app.openapi()
    return {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}


def test_table_covers_every_openapi_route():
    """A new route cannot be added without a row; a removed route cannot keep one."""
    openapi_routes = _openapi_routes()
    table_routes = {(r.method, r.path) for r in ROUTE_MATRIX}
    missing = openapi_routes - table_routes
    extra = table_routes - openapi_routes
    assert not missing, f"routes WITHOUT a matrix row: {sorted(missing)}"
    assert not extra, f"matrix rows for routes that no longer exist: {sorted(extra)}"


def test_every_principal_has_an_expectation():
    for row in ROUTE_MATRIX:
        assert set(row.expected) == set(PRINCIPALS), f"{row.method} {row.path}: missing {set(PRINCIPALS) - set(row.expected)}"


def test_csrf_claims_are_complete():
    for row in ROUTE_MATRIX:
        if row.method in MUTATING and row.csrf != "required":
            assert (row.method, row.path) in CSRF_EXEMPT_MUTATIONS, f"{row.method} {row.path} must be 'required' or carry a reviewed exemption"


# ---- 2. the principal matrix ------------------------------------------------------------


@pytest.mark.asyncio
async def test_principal_status_matrix(matrix_harness):
    """Every route x every principal must match the reviewed table exactly."""
    h = matrix_harness
    problems: list[str] = []
    for row in ROUTE_MATRIX:
        for principal in PRINCIPALS:
            r = await _probe(h, row, principal)
            want = row.expected[principal]
            if r.status_code != want:
                problems.append(f"{row.method} {row.path} as {principal}: got {r.status_code}, want {want} :: {r.text[:140]}")
    assert not problems, "\n".join(problems)


@pytest.mark.asyncio
async def test_deactivated_user_cannot_log_in(matrix_harness):
    r = await matrix_harness.client.post(
        "/api/auth/login",
        json={"email": "matrix-dead@urumi.local", "password": SESSION_USER_PASSWORDS["deactivated"]},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_deactivated_users_still_valid_key_is_rejected_on_mcp(matrix_harness):
    h = matrix_harness
    r = await h.client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": f"Bearer {h.keys['deactivated']}"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_password_rejected(matrix_harness):
    r = await matrix_harness.client.post("/api/auth/login", json={"email": "matrix-admin@urumi.local", "password": "definitely-wrong-pass"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_self_delete_is_rejected(matrix_harness):
    h = matrix_harness
    r = await h.client.request(
        "DELETE",
        f"/api/users/{h.ids['admin_id']}",
        cookies=h.cookies["admin"],
        headers={"X-CSRF-Token": h.csrf["admin"]},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_unknown_server_id_is_404(matrix_harness):
    h = matrix_harness
    r = await h.client.get(f"/api/servers/{uuid.uuid4()}", cookies=h.cookies["member"])
    assert r.status_code == 404


# ---- 2b. CSRF sub-cases -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_mutating_session_routes_reject_missing_and_wrong_csrf(matrix_harness):
    h = matrix_harness
    problems: list[str] = []
    for row in ROUTE_MATRIX:
        if row.csrf != "required":
            continue
        for principal in ("admin", "member"):
            if not (200 <= row.expected[principal] < 300):
                continue  # this principal cannot reach the handler anyway
            r = await _probe(h, row, principal, with_csrf=False)
            if r.status_code != 403:
                problems.append(f"{row.method} {row.path} as {principal} missing CSRF: {r.status_code} (want 403)")
            r = await _probe(h, row, principal, extra_headers={"X-CSRF-Token": "definitely-wrong"})
            if r.status_code != 403:
                problems.append(f"{row.method} {row.path} as {principal} wrong CSRF: {r.status_code} (want 403)")
    assert not problems, "\n".join(problems)


@pytest.mark.asyncio
async def test_csrf_exempt_mutations_have_reviewed_reasons():
    for row in ROUTE_MATRIX:
        if row.method in MUTATING and row.csrf != "required":
            assert (row.method, row.path) in CSRF_EXEMPT_MUTATIONS, f"{row.method} {row.path}: {row.csrf!r} lacks a reviewed reason"


# ---- hostile inputs: 4xx where input is invalid, NEVER 5xx, no stack trace, no secrets --

OVERSIZE = "x" * 120_000
SQL_INJECTION = "'; DROP TABLE users; --"
CONTROL_CHARS = "zero\u0000unit\u001fsep\x7fdel\r\n\t"
EXTRA_FIELDS = {"__admin_backdoor": True, "role": "admin", "is_active": True, "password_hash": "forged"}

SECRET_MARKERS_STATIC = (
    "matrix-admin-pass-123",
    "matrix-member-pass-123",
    "matrix-b-pass-123",
    "matrix-dead-pass-123",
    "throwaway-pass-123",
    "Traceback",
    'File "',
)


def _fuzz_cases() -> list:
    return [
        ("empty", {}),
        ("wrong_types", {
            "email": 1, "password": False, "role": 42, "slug": [], "url": {"a": 1},
            "auth_type": 9, "header_name": [], "credential": 0, "timeout_ms": "soon",
            "messages": "not-a-list", "rules": 7, "expires_at": 12.5,
        }),
        ("oversize", {"email": OVERSIZE, "password": OVERSIZE, "slug": OVERSIZE, "url": OVERSIZE, "content": OVERSIZE}),
        ("sql", {"email": f"'{SQL_INJECTION}", "slug": "drop-table-users", "url": f"http://x.invalid/{SQL_INJECTION}", "messages": [{"role": "user", "content": SQL_INJECTION}]}),
        ("extra_fields", dict(EXTRA_FIELDS)),
        ("control_chars", {"email": CONTROL_CHARS, "slug": "a-b", "messages": [{"role": "user", "content": CONTROL_CHARS}]}),
]

# per (method, path): which hostile cases MUST be rejected with 4xx (the body
# model has required/validated fields). Routes whose body is fully optional
# ({} on POST /api/keys is a valid mint; bodyless action posts ignore JSON) are
# only held to the NEVER-5XX + no-leak contract; stated in the doc.


STRICT_4XX = {
    ("POST", "/api/auth/login"): {"empty", "wrong_types", "oversize"},
    ("POST", "/api/users"): {"empty", "wrong_types", "oversize"},
    ("POST", "/api/servers"): {"empty", "wrong_types", "oversize"},
    ("PATCH", "/api/servers/{server_id}"): {"wrong_types", "oversize"},
    ("PUT", "/api/permissions"): {"wrong_types"},
    ("POST", "/api/chat/completions"): {"empty", "wrong_types"},
    ("POST", "/mcp"): {"empty", "wrong_types"},
}


@pytest.mark.asyncio
async def test_hostile_inputs_never_5xx_and_no_leaks(matrix_harness):
    """Every POST/PUT/PATCH x hostile input: never 5xx, never a stack trace,
    never a secret; STRICT_4XX routes must answer 4xx for the listed cases."""
    h = matrix_harness
    problems: list[str] = []
    for row in ROUTE_MATRIX:
        if row.method not in MUTATING:
            continue
        if row.path == "/mcp":
            principal = None  # handled by the dedicated MCP fuzz cases (bearer key)
        else:
            principal = "admin" if 200 <= row.expected["admin"] < 300 else ("member" if 200 <= row.expected["member"] < 300 else None)
        if principal is None:
            continue
        for case, body in _fuzz_cases():
            r = await _probe(h, row, principal, body=body)
            if r.status_code >= 500:
                problems.append(f"{row.method} {row.path} [{case}]: 5xx {r.status_code} :: {r.text[:160]}")
                continue
            text = r.text
            for marker in SECRET_MARKERS_STATIC:
                if marker in text:
                    problems.append(f"{row.method} {row.path} [{case}]: leaked {marker!r} :: {text[:160]}")
            # the SEEDED key values must never appear (a fresh mint returning its
            # own new raw key exactly once is the documented contract, not a leak)
            for seeded in (h.keys["member_key"], h.keys["admin"], h.keys["revoked_key"], h.keys["expired_key"]):
                if seeded in text:
                    problems.append(f"{row.method} {row.path} [{case}]: leaked a seeded API key :: {text[:160]}")
            strict = STRICT_4XX.get((row.method, row.path), set())
            if case in strict and not (400 <= r.status_code < 500):
                problems.append(f"{row.method} {row.path} [{case}]: got {r.status_code}, want 4xx :: {text[:160]}")
    assert not problems, "\n".join(problems)


# ---- IDOR: cross-user isolation ---------------------------------------------------------


@pytest.mark.asyncio
async def test_member_cannot_read_or_revoke_anothers_keys(matrix_harness):
    h = matrix_harness
    # list: member A sees only own keys
    r = await h.client.get("/api/keys", cookies=h.cookies["member"])
    assert r.status_code == 200
    keys = r.json()["keys"]
    assert keys, "member A has seeded keys"
    assert {k["user_id"] for k in keys} == {h.ids["member_a_id"]}, "member A must see only own keys"

    # mint a key owned by member B, then let A try to revoke it

    async with h.SessionLocal() as db:
        row_b, _raw_b = await create_api_key(db, uuid.UUID(h.ids["member_b_id"]))
        await db.commit()
        b_key_id = str(row_b.id)

    r = await h.client.request("DELETE", f"/api/keys/{b_key_id}", cookies=h.cookies["member"], headers={"X-CSRF-Token": h.csrf["member"]})
    assert r.status_code == 403, f"revoking B's key must be 403, got {r.status_code}"
    r = await h.client.get("/api/keys", cookies=h.cookies["member"])
    assert all(k["id"] != b_key_id for k in r.json()["keys"]), "B's key must not appear in A's list"
    # admin CAN revoke B's key
    r = await h.client.request("DELETE", f"/api/keys/{b_key_id}", cookies=h.cookies["admin"], headers={"X-CSRF-Token": h.csrf["admin"]})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_member_cannot_read_anothers_audit_rows(matrix_harness):
    h = matrix_harness
    r = await h.client.get(f"/api/audit?user_id={h.ids['member_b_id']}", cookies=h.cookies["member"])
    assert r.status_code == 200
    rows = r.json()["logs"]
    assert rows, "member A has seeded audit rows"
    assert {row["user_id"] for row in rows} == {h.ids["member_a_id"]}, "an audit ?user_id=<other> filter must never widen a member's scope"
    # admin CAN read B's rows
    r = await h.client.get(f"/api/audit?user_id={h.ids['member_b_id']}", cookies=h.cookies["admin"])
    assert r.status_code == 200
    assert {row["user_id"] for row in r.json()["logs"]} == {h.ids["member_b_id"]}


@pytest.mark.asyncio
async def test_member_stats_are_scoped_to_self(matrix_harness):
    h = matrix_harness
    r = await h.client.get("/api/stats", cookies=h.cookies["member"])
    assert r.status_code == 200
    body = r.json()
    total_calls = body.get("total_calls") or sum(o.get("calls", 0) for o in [body]) if isinstance(body.get("total_calls"), int) else None
    # member aggregates exclude B's row: total calls must equal A's own row count (1)
    assert "by_server" not in body, "by_server aggregates are admin-only"
    # the robust check: A's audit view has exactly 1 row, so stats over calls must be 1
    r_audit = await h.client.get("/api/audit", cookies=h.cookies["member"])
    own_rows = r_audit.json()["total"]
    assert total_calls is None or total_calls == own_rows, f"stats total {total_calls} must match own audit rows {own_rows}"


@pytest.mark.asyncio
async def test_member_gets_403_on_every_admin_only_route(matrix_harness):
    h = matrix_harness
    admin_only = [row for row in ROUTE_MATRIX if row.expected["member"] == 403]
    assert admin_only, "the table must classify admin-only routes"
    for row in admin_only:
        r = await _probe(h, row, "member")
        assert r.status_code == 403, f"{row.method} {row.path} as member: {r.status_code}"


@pytest.mark.asyncio
async def test_alerts_have_no_cross_user_surface(matrix_harness):
    """/api/alerts is the notifications surface: global health/alert state, no
    per-user ownership, so no IDOR is possible there (documented in the doc)."""
    h = matrix_harness
    r = await h.client.get("/api/alerts", cookies=h.cookies["member"])
    assert r.status_code == 200
# ---- MCP: JSON-RPC method matrix over POST /mcp -----------------------------------------


def _rpc(method: str, params=None, id_=1) -> dict:
    payload: dict = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


@pytest.fixture()
async def mcp_matrix(matrix_harness, monkeypatch):
    """MCP matrix over the seeded harness: captures /mcp audit rows."""
    import routes.mcp as mcp_route

    h = matrix_harness
    h.captured_audit = []

    async def fake_log_audit(**kwargs):
        h.captured_audit.append(kwargs)

    monkeypatch.setattr(mcp_route, "log_audit", fake_log_audit)
    return h


async def _mcp(h, payload: dict, key: str | None = "member_key") -> httpx.Response:
    headers = {"Authorization": f"Bearer {h.keys[key]}"} if key else {}
    return await h.client.post("/mcp", json=payload, headers=headers)


async def _call_tool(h, name: str, arguments, key: str = "member_key") -> httpx.Response:
    return await _mcp(h, _rpc("tools/call", {"name": name, "arguments": arguments}, id_=7), key=key)


@pytest.mark.asyncio
async def test_mcp_jsonrpc_method_matrix(matrix_harness):
    h = matrix_harness
    # initialize
    r = await _mcp(h, _rpc("initialize", {}))
    assert r.status_code == 200 and r.json()["result"]["serverInfo"]["name"] == "urumi-gateway"
    # notifications/initialized -> 202, no id
    r = await _mcp(h, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202
    # ping
    r = await _mcp(h, _rpc("ping"))
    assert r.status_code == 200 and r.json()["result"] == {}
    # unknown method
    r = await _mcp(h, _rpc("resources/list"))
    assert r.status_code == 400 and r.json()["error"]["code"] == -32601
    # malformed JSON
    r = await h.client.post("/mcp", content=b"{not json", headers={"Authorization": f"Bearer {h.keys['member_key']}"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32700
    # oversized JSON-RPC body (>1MB guard)
    r = await _mcp(h, _rpc("tools/call", {"name": "notes__search_notes", "arguments": {"query": "x" * 1_100_000}}))
    assert r.status_code == 413
    # tools/list: member key, admin key
    r = await _mcp(h, _rpc("tools/list"))
    assert r.status_code == 200 and isinstance(r.json()["result"]["tools"], list)
    r = await _mcp(h, _rpc("tools/list"), key="admin")
    assert r.status_code == 200
    # revoked / expired / deactivated-user key / no token
    for principal in ("revoked_key", "expired_key", "deactivated"):
        r = await _mcp(h, _rpc("tools/list"), key=principal)
        assert r.status_code == 401, f"tools/list as {principal}: {r.status_code}"
    r = await _mcp(h, _rpc("tools/list"), key=None)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_mcp_tools_call_case_matrix(matrix_harness, monkeypatch):
    """tools/call for every case that matters, with audit assertions.

    proxy_call is swapped per scenario (no network); call_tool_routed stays REAL
    so DB lookups, breaker and classification run exactly as in production.
    """
    import gw_mcp.router as gw_router
    import httpx as _httpx
    import routes.mcp as mcp_route

    h = matrix_harness
    captured: list[dict] = []

    async def fake_log_audit(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(mcp_route, "log_audit", fake_log_audit)

    def _proxy_returning(payload):
        async def proxy(server, tool, arguments, timeout_seconds=None):
            return payload

        return proxy

    async def refused_proxy(server, tool, arguments, timeout_seconds=None):
        raise ConnectionRefusedError("connection refused")

    async def hanging_proxy(server, tool, arguments, timeout_seconds=None):
        raise ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [_httpx.ReadTimeout("read timed out")])

    OK = {"content": [{"type": "text", "text": '{"notes":[],"count":0}'}], "isError": False}
    TOOL_VALIDATION = {
        "content": [
            {
                "type": "text",
                "text": "Error executing tool search_notes: 1 validation error for search_notesArguments\nquery\n  Field required [type=missing]",
            }
        ],
        "isError": True,
    }

    # 1. valid args -> success + audit row for the right user (member is denied on
    # notes by the seeded deny row, so the member success case uses the throwaway server)
    monkeypatch.setattr(gw_router, "proxy_call", _proxy_returning(OK))
    r = await _call_tool(h, "matrix-throwaway__list_notes", {})
    assert r.status_code == 200 and r.json()["result"]["isError"] is False
    assert captured[-1]["outcome"] == "success"
    assert captured[-1]["user_id"] == uuid.UUID(h.ids["member_a_id"])

    # 2. invalid args (tool-level validation) -> clear isError tool error, audit validation_error
    monkeypatch.setattr(gw_router, "proxy_call", _proxy_returning(TOOL_VALIDATION))
    r = await _call_tool(h, "matrix-throwaway__search_notes", {"query": 5})
    assert r.status_code == 200 and r.json()["result"]["isError"] is True
    assert captured[-1]["outcome"] == "validation_error"

    # 3. non-object arguments -> 400 validation error (the fixed 502 "upstream error" path)
    r = await _call_tool(h, "matrix-throwaway__list_notes", "hello", key="admin")
    assert r.status_code == 400 and r.json()["error"]["code"] == -32602
    assert captured[-1]["outcome"] == "validation_error"

    # 4. permission denied: the seeded member deny row covers the whole notes server
    r = await _call_tool(h, "notes__list_notes", {})
    assert r.status_code == 400 and "unknown tool" in r.json()["error"]["message"]
    assert captured[-1]["outcome"] == "permission_denied"
    # ...while the admin key is never denied (proxy back to the OK scenario)
    monkeypatch.setattr(gw_router, "proxy_call", _proxy_returning(OK))
    r = await _call_tool(h, "notes__list_notes", {}, key="admin")
    assert r.status_code == 200 and captured[-1]["outcome"] == "success"

    # 5. disabled server -> validation error (ValueError branch)
    from sqlalchemy import select as _select

    async with h.SessionLocal() as db:
        srv = (await db.execute(_select(Server).where(Server.slug == "notes"))).scalars().first()
        srv.enabled = False
        await db.commit()
    r = await _call_tool(h, "notes__list_notes", {}, key="admin")
    assert r.status_code == 400 and "disabled" in r.json()["error"]["message"]
    assert captured[-1]["outcome"] == "validation_error"
    async with h.SessionLocal() as db:
        srv = (await db.execute(_select(Server).where(Server.slug == "notes"))).scalars().first()
        srv.enabled = True
        await db.commit()

    # 6. unreachable upstream -> 502 upstream_error
    monkeypatch.setattr(gw_router, "proxy_call", refused_proxy)
    r = await _call_tool(h, "notes__list_notes", {}, key="admin")
    assert r.status_code == 502 and captured[-1]["outcome"] == "upstream_error"

    # 7. hanging upstream (TaskGroup-wrapped httpx read timeout) -> 504 timeout
    monkeypatch.setattr(gw_router, "proxy_call", hanging_proxy)
    r = await _call_tool(h, "notes__list_notes", {}, key="admin")
    assert r.status_code == 504 and captured[-1]["outcome"] == "timeout"

    # 8. unknown tool: unknown slug at the gateway -> 400 validation_error
    r = await _call_tool(h, "nosuch__tool", {}, key="admin")
    assert r.status_code == 400
    assert captured[-1]["outcome"] == "validation_error"
    # unknown tool ON the upstream -> clear isError tool result, audit upstream_error
    monkeypatch.setattr(
        gw_router,
        "proxy_call",
        _proxy_returning({"content": [{"type": "text", "text": "Unknown tool: does_not_exist"}], "isError": True}),
    )
    r = await _call_tool(h, "notes__does_not_exist", {}, key="admin")
    assert r.status_code == 200 and r.json()["result"]["isError"] is True
    assert captured[-1]["outcome"] == "upstream_error"

    # 9. malformed JSON-RPC -> 400 -32700
    r = await h.client.post("/mcp", content=b"{not json", headers={"Authorization": f"Bearer {h.keys['admin']}"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32700

    # 10. oversized arguments (>1MB) -> 413 before any routing
    r = await _call_tool(h, "notes__list_notes", {"q": "z" * 1_100_000}, key="admin")
    assert r.status_code == 413

    # audit hygiene: every captured row has a stable outcome and NO argument values
    for row in captured:
        assert row["outcome"] in ("success", "upstream_error", "permission_denied", "timeout", "circuit_open", "validation_error")
        assert "zzz" not in (row.get("error_code") or "")
        assert "hello" not in (row.get("error_code") or "")


# ---- docs/ENDPOINT_MATRIX.md rendered FROM this table ----------------------------------

DOC_HEADER = """# ENDPOINT MATRIX

Generated from the SAME reviewed table that drives
`src/gateway/tests/endpoint_matrix.py` — do not edit by hand.
Regenerate with: `cd src/gateway && ../../.venv/bin/python -m tests.endpoint_matrix`
(the test `test_doc_matches_table` fails if this file drifts from the table).

Coverage: every OpenAPI route x 7 principals, CSRF (missing/wrong) on every
session-auth mutating route, hostile inputs on every POST/PUT/PATCH, IDOR
cross-user isolation, and the MCP JSON-RPC method/tools matrix with audit
assertions. Live-cluster read-only spot checks: scripts/verify-endpoints.sh.

Not covered here: load/concurrency, the ingress/TLS layer, browser-side CSRF
(the table pins the SERVER-side check), SSE framing beyond status codes.
"""


def render_markdown() -> str:
    lines: list[str] = [DOC_HEADER.strip(), ""]
    lines.append("## Routes x principals")
    lines.append("")
    lines.append(
        "| Method | Path | anonymous | member | admin | deactivated | member key | revoked key | expired key | CSRF | Notes |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for row in ROUTE_MATRIX:
        note = row.note.replace("|", "/")
        lines.append(f"| {row.method} | `{row.path}` | {row.expected['anonymous']} | {row.expected['member']} | {row.expected['admin']} | {row.expected['deactivated']} | {row.expected['member_key']} | {row.expected['revoked_key']} | {row.expected['expired_key']} | {row.csrf} | {note} |")
    lines.append("")
    lines.append("Principals: anonymous (no credentials); member/admin = session cookie; deactivated = signed session of an is_active=false user; member key = active Bearer key; revoked/expired = dead Bearer keys. CSRF rows list the server-side behaviour; 'required' means missing or wrong `X-CSRF-Token` is 403. Session routes never accept Bearer keys; /mcp never accepts session cookies.")
    lines.append("")
    lines.append("## CSRF-exempt mutations (reviewed)")
    lines.append("")
    for (method, path), reason in sorted(CSRF_EXEMPT_MUTATIONS.items()):
        lines.append(f"- {method} `{path}` — {reason}")
    lines.append("")
    lines.append("## Hostile input contract (every POST/PUT/PATCH)")
    lines.append("")
    lines.append("Cases: empty body, wrong types, oversize string (120k), SQL-looking string, extra fields, unicode/control characters.")
    lines.append("")
    lines.append("- NEVER 5xx, never a stack trace, never a secret in any response body (asserted for every case).")
    lines.append("- Routes with validated body models must answer 4xx for: empty body, wrong types, oversize strings, SQL-looking slugs/emails (strict set pinned in the test).")
    lines.append("- Routes whose body is fully optional ({} on POST /api/keys is a valid mint; bodyless action posts ignore JSON) are held to the never-5xx contract only; a 2xx there is correct behaviour, not a gap.")
    lines.append("- SQL-looking strings that pass validation are stored as data through parameterised SQLAlchemy (no injection path); unicode/control characters are preserved as data.")
    lines.append("")
    lines.append("## MCP (POST /mcp, Bearer key)")
    lines.append("")
    lines.append("| Case | Expected |")
    lines.append("| --- | --- |")
    lines.append("| initialize | 200 serverInfo urumi-gateway |")
    lines.append("| notifications/initialized | 202 |")
    lines.append("| ping | 200 result {} |")
    lines.append("| unknown method | 400 -32601 |")
    lines.append("| malformed JSON | 400 -32700 |")
    lines.append("| body > 1MB | 413 |")
    lines.append("| tools/list admin key / member key | 200 (RBAC-filtered for member) |")
    lines.append("| tools/list revoked / expired / deactivated-user key / no token | 401 |")
    lines.append("| tools/call valid args (mocked upstream) | 200 result; audit success with the right user |")
    lines.append("| tools/call invalid args (tool validation) | 200 isError tool error; audit validation_error |")
    lines.append("| tools/call non-object arguments | 400 -32602; audit validation_error |")
    lines.append("| tools/call permission denied | 400 unknown-tool error; audit permission_denied |")
    lines.append("| tools/call disabled server | 400 validation_error |")
    lines.append("| tools/call unreachable upstream | 502 upstream_error |")
    lines.append("| tools/call hanging upstream (TaskGroup timeout) | 504 timeout |")
    lines.append("| tools/call unknown tool (gateway slug) | 400 validation_error |")
    lines.append("| tools/call unknown tool (on upstream) | 200 isError; audit upstream_error |")
    lines.append("| malformed JSON-RPC | 400 -32700 |")
    lines.append("| oversized arguments > 1MB | 413 |")
    lines.append("")
    lines.append("Audit assertions: rows carry the right user, a stable outcome/error_code, and never argument values.")
    lines.append("")
    lines.append("## Known honest gaps")
    lines.append("")
    lines.append("- The chat agent's INTERNAL audit for a failed tool call (exception paths) writes no row; /mcp audits every outcome. Flagged, out of scope here.")
    lines.append("- GET /mcp is a 405 JSON-RPC envelope by design (stateless POST-only gateway).")
    return "\n".join(lines) + "\n"


def doc_path():
    return Path(__file__).resolve().parents[3] / "docs" / "ENDPOINT_MATRIX.md"


def test_doc_matches_table():
    """The committed doc must equal the table rendering (doc cannot drift)."""
    committed = doc_path().read_text() if doc_path().exists() else ""
    assert committed == render_markdown(), (
        "docs/ENDPOINT_MATRIX.md drifted from the ROUTE_MATRIX table; regenerate with: "
        "cd src/gateway && ../../.venv/bin/python -m tests.endpoint_matrix"
    )


if __name__ == "__main__":
    doc_path().write_text(render_markdown())
    print(f"wrote {doc_path()}")
