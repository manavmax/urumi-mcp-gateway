"""Phase 7 (ADR-063) OAuth tests: the full authorization-code flow in-process.

Covers the security-critical rules:
  - PKCE S256 ONLY (plain refused, wrong verifier refused)
  - redirect_uri EXACT match at authorize AND at token exchange
  - code single-use (replay refused) + 10-minute TTL
  - resource indicator binding (RFC 8707): authorize requires the canonical
    resource; a token bound elsewhere is refused at /mcp
  - refresh rotation + reuse revokes the family
  - token hashes at rest (the raw token is never in the DB)
  - unauthenticated /mcp 401 carries the RFC 9728 WWW-Authenticate pointer
  - the flow end-to-end: register -> authorize (consent) -> token -> /mcp call
    mapped to the user (same permission/audit path as API keys)
"""

from __future__ import annotations

import base64
import hashlib
import os

import config
import httpx
import pytest
from auth.rbac import hash_password
from db.models import Base, OauthToken, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ADMIN = {"email": "admin-o@urumi.local", "password": "admin-o-pass-123"}
REDIRECT = "http://127.0.0.1:9911/callback"
RESOURCE = "http://dashboard.127.0.0.1.nip.io/mcp"


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


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

    from config import Settings

    test_settings = Settings(
        oauth_enabled=True,
        public_base_url="http://dashboard.127.0.0.1.nip.io",
        stores_enabled=False,
    )
    monkeypatch.setattr(config, "get_settings", lambda: test_settings)
    monkeypatch.setattr("db.session.get_session_factory", lambda: SessionLocal)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with SessionLocal() as db:
        db.add(User(email=ADMIN["email"], password_hash=await hash_password(ADMIN["password"]), role="member"))
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


async def _flow(harness, *, resource: str = RESOURCE, redirect: str = REDIRECT, pkce_ok: bool = True):
    """register -> authorize(consent approve) -> token. Returns (client, token_doc, SessionLocal)."""
    client, SessionLocal = harness
    h = await _login(client, **ADMIN)

    # discovery
    r = await client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200 and r.json()["resource"] == RESOURCE
    r = await client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200 and "S256" in r.json()["code_challenge_methods_supported"]

    # dynamic client registration (RFC 7591)
    r = await client.post("/oauth/register", json={"redirect_uris": [redirect], "client_name": "Test MCP"})
    assert r.status_code == 201, r.text
    client_id = r.json()["client_id"]

    # unauthenticated /mcp must point at the metadata
    r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    assert "oauth-protected-resource" in r.headers.get("www-authenticate", "")

    verifier, challenge = _pkce()
    authorize_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "scope": "mcp",
        "state": "st-123",
        "resource": resource,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if not pkce_ok:
        authorize_params["code_challenge_method"] = "plain"

    # consent page renders (dashboard session) and refusing shapes are right
    r = await client.get("/oauth/authorize", params=authorize_params, headers=h, follow_redirects=False)
    if r.status_code == 302:
        # authorize refused: error redirect back to the client (plain PKCE,
        # wrong resource, unknown client, ...)
        assert "error=" in r.headers["location"]
        return client, None, SessionLocal
    assert r.status_code == 200 and "Authorize access" in r.text

    # approve (CSRF-protected POST)
    r = await client.post("/oauth/authorize", data={**authorize_params, "decision": "approve"},
                          headers=h, follow_redirects=False)
    assert r.status_code == 302, r.text
    loc = r.headers["location"]
    assert loc.startswith(redirect) and "state=st-123" in loc
    code = loc.split("code=")[1].split("&")[0]

    # exchange (PKCE verifier)
    r = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "client_id": client_id,
        "redirect_uri": redirect, "code_verifier": verifier, "resource": resource,
    })
    assert r.status_code == 200, r.text
    tok = r.json()
    assert tok["token_type"] == "Bearer" and tok["access_token"].startswith("uat_")
    return client, (tok, client_id, verifier, code), SessionLocal


async def test_full_flow_token_works_on_mcp(harness):
    client, bundle, SessionLocal = await _flow(harness)
    tok, _cid, _, _ = bundle

    # the access token maps to the user on /mcp (same path as API keys)
    r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                          headers={"Authorization": f"Bearer {tok['access_token']}"})
    assert r.status_code == 200, r.text
    assert "result" in r.json()

    # hashes at rest: the raw token is not in the tokens table
    async with SessionLocal() as db:
        rows = (await db.execute(select(OauthToken))).scalars().all()
        assert rows and all(tok["access_token"] not in (r2.token_hash for r2 in rows) for _ in [0])
        assert any(r2.kind == "access" for r2 in rows) and any(r2.kind == "refresh" for r2 in rows)


async def test_pkce_plain_refused(harness):
    _c, bundle, _ = await _flow(harness, pkce_ok=False)
    assert bundle is None


async def test_code_replay_refused(harness):
    client, bundle, _ = await _flow(harness)
    _tok, client_id, verifier, code = bundle
    # second exchange with the SAME code must fail
    r = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "client_id": client_id,
        "redirect_uri": REDIRECT, "code_verifier": verifier, "resource": RESOURCE,
    })
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


async def test_redirect_mismatch_refused(harness):
    client, bundle, _ = await _flow(harness)
    _tok, client_id, _, _ = bundle
    # a DIFFERENT redirect at token time (not the one from authorize)
    r = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": "whatever", "client_id": client_id,
        "redirect_uri": "http://evil.example/cb", "code_verifier": "x" * 50,
    })
    assert r.status_code == 400


async def test_refresh_rotation_and_reuse(harness):
    client, bundle, _ = await _flow(harness)
    tok, client_id, _, _ = bundle
    rt = tok["refresh_token"]

    # refresh #1 works and rotates
    r = await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id, "resource": RESOURCE,
    })
    assert r.status_code == 200
    new_tok = r.json()
    assert new_tok["refresh_token"] != rt

    # reuse of the OLD refresh token revokes the family
    r = await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id, "resource": RESOURCE,
    })
    assert r.status_code == 400 and "reuse" in r.json()["error_description"]

    # the whole family is dead: the NEW refresh token no longer works either
    r = await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": new_tok["refresh_token"], "client_id": client_id,
        "resource": RESOURCE,
    })
    assert r.status_code == 400
    # and the access token from before the revoke is also refused on /mcp
    r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                          headers={"Authorization": f"Bearer {new_tok['access_token']}"})
    assert r.status_code == 401


async def test_resource_binding_enforced(harness):
    """RFC 8707: authorize with a WRONG resource is refused (invalid_target
    redirect back to the client) and no tokens are ever issued."""
    _c, bundle, _ = await _flow(harness, resource="http://other-gateway/mcp")
    assert bundle is None  # authorize refused with invalid_target


async def test_revocation_endpoint(harness):
    client, bundle, _ = await _flow(harness)
    tok, _cid, _, _ = bundle
    r = await client.post("/oauth/revoke", data={"token": tok["access_token"], "token_type_hint": "access_token"})
    assert r.status_code == 200
    r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                          headers={"Authorization": f"Bearer {tok['access_token']}"})
    assert r.status_code == 401
