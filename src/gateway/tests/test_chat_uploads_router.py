"""POST /api/chat/uploads + upload references through the REAL router (F3, ADR-035).

Real FastAPI app, real session-cookie + CSRF chain, real sqlite database — only
the LLM is absent (the upload route never needs it; the completions route answers
before the LLM when a message references a bad upload).

Pinned here:
  - anonymous -> 401; missing CSRF token -> 403
  - a valid png is stored owner-bound (row.user_id == uploader); the response
    never echoes bytes
  - wrong magic bytes (a GIF renamed .png) and SVG payloads -> 415; the claimed
    multipart content type is ignored
  - over-cap upload -> 413
  - per-user rate limit: the 11th upload in a minute is 429, another user's own
    bucket is unaffected
  - another user's upload id in chat is 404 (owner-bound, no existence leak)
  - an expired upload reference in chat is 410
  - a text-only model chain gets a clear message instead of a provider error
  - uploading purges expired rows
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from auth.rbac import hash_password
from db.models import Base, ChatUpload, Server, User
from db.session import get_db
from httpx import ASGITransport
from main import create_app
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

USER_A = {"email": "member-a@urumi.local", "password": "member-a-pass-123"}
USER_B = {"email": "member-b@urumi.local", "password": "member-b-pass-123"}

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_bytes(w: int = 2, h: int = 2) -> bytes:

    img = Image.new("RGBA", (w, h), (200, 30, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
async def harness():
    """Real app + real sqlite DB seeded with two members (no LLM needed)."""
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
        user_a = User(email=USER_A["email"], password_hash=await hash_password(USER_A["password"]), role="member")
        user_b = User(email=USER_B["email"], password_hash=await hash_password(USER_B["password"]), role="member")
        db.add_all([user_a, user_b])
        await db.flush()
        db.add(Server(slug="woo", url="http://woo.invalid:8000/mcp", auth_type="none", timeout_ms=5000))
        await db.commit()

    import routes.chat_uploads as uploads_mod

    uploads_mod._rate_buckets.clear()

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, SessionLocal, {"app": app, "user_a": user_a, "user_b": user_b}
    await engine.dispose()


async def _login(client: httpx.AsyncClient, email: str, password: str) -> dict:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


@pytest.mark.asyncio
async def test_upload_requires_authentication_and_csrf(harness):
    client, _, _ = harness
    r = await client.post("/api/chat/uploads", files={"file": ("x.png", PNG_MAGIC + b"0" * 20, "image/png")})
    assert r.status_code == 401, "anonymous uploads are refused"


@pytest.mark.asyncio
async def test_upload_without_csrf_is_403(harness):
    client, _, _ = harness
    await _login(client, USER_A["email"], USER_A["password"])  # cookie only, NO CSRF header
    # session cookie WITHOUT the CSRF header: refused before any bytes are read
    r = await client.post("/api/chat/uploads", files={"file": ("x.png", png_bytes(2, 2), "image/png")})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_valid_png_upload_stores_owner_bound_row(harness):
    client, session_local, ids = harness
    headers = await _login(client, USER_A["email"], USER_A["password"])
    r = await client.post("/api/chat/uploads", files={"file": ("cat.png", png_bytes(), "image/png")}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mime"] == "image/png" and body["size"] > 0
    assert "iVBOR" not in r.text  # the response never echoes the bytes
    async with session_local() as db:
        rows = (await db.execute(select(ChatUpload))).scalars().all()
        assert len(rows) == 1
        assert str(rows[0].user_id) == str(ids["user_a"].id)
        assert rows[0].mime == "image/png"
        assert rows[0].expires_at > rows[0].created_at


@pytest.mark.asyncio
async def test_upload_rejects_gif_renamed_png_and_svg(harness):
    client, _, _ = harness
    headers = await _login(client, USER_A["email"], USER_A["password"])
    # the claimed multipart type is image/png; the magic bytes say GIF
    r = await client.post(
        "/api/chat/uploads",
        files={"file": ("cat.png", b"GIF89a" + b"0" * 32, "image/png")},
        headers=headers,
    )
    assert r.status_code == 415
    assert r.json()["code"] == "UNSUPPORTED_IMAGE_TYPE"
    r = await client.post(
        "/api/chat/uploads",
        files={"file": ("evil.png", b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/png")},
        headers=headers,
    )
    assert r.status_code == 415


@pytest.mark.asyncio
async def test_upload_oversize_is_413(monkeypatch, harness):
    client, _, _ = harness

    class _S:
        image_upload_max_bytes = 10
        chat_upload_ttl_seconds = 900

    import routes.chat_uploads as uploads_mod

    monkeypatch.setattr(uploads_mod, "get_settings", lambda: _S())
    headers = await _login(client, USER_A["email"], USER_A["password"])
    r = await client.post(
        "/api/chat/uploads",
        files={"file": ("x.png", PNG_MAGIC + b"0" * 64, "image/png")},
        headers=headers,
    )
    assert r.status_code == 413
    assert r.json()["code"] == "IMAGE_TOO_LARGE"


@pytest.mark.asyncio
async def test_upload_rate_limit_is_per_user_10_per_minute(harness):
    from httpx import ASGITransport

    client, _, ids = harness
    from routes import chat_uploads as uploads_mod

    uploads_mod._rate_buckets.clear()
    headers_a = await _login(client, USER_A["email"], USER_A["password"])
    for i in range(10):
        r = await client.post(
            "/api/chat/uploads",
            files={"file": (f"x{i}.png", png_bytes(), "image/png")},
            headers=headers_a,
        )
        assert r.status_code == 200, f"upload {i + 1} -> {r.status_code}"
    r = await client.post(
        "/api/chat/uploads", files={"file": ("x.png", png_bytes(), "image/png")}, headers=headers_a
    )
    assert r.status_code == 429, "the 11th upload inside the minute is refused"
    # a different user has their own bucket (separate client = separate cookie jar)

    async with httpx.AsyncClient(transport=ASGITransport(app=ids["app"]), base_url="http://test") as client_b:
        headers_b = await _login(client_b, USER_B["email"], USER_B["password"])
        r = await client_b.post(
            "/api/chat/uploads", files={"file": ("x.png", png_bytes(), "image/png")}, headers=headers_b
        )
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_other_users_upload_reference_is_404(harness):
    from httpx import ASGITransport

    client, _, ids = harness
    headers_a = await _login(client, USER_A["email"], USER_A["password"])
    async with httpx.AsyncClient(transport=ASGITransport(app=ids["app"]), base_url="http://test") as client_b:
        # user B gets an independent session (own cookie jar), so A's cookie is
        # not overwritten
        headers_b = await _login(client_b, USER_B["email"], USER_B["password"])
        r = await client.post("/api/chat/uploads", files={"file": ("cat.png", png_bytes(), "image/png")}, headers=headers_a)
        assert r.status_code == 200, r.text
        upload_id = r.json()["upload_id"]

        # user A's own reference passes the ownership check (it then reaches the
        # LLM-config stage of the route)
        r = await client.post(
            "/api/chat/completions",
            json={"messages": [{"role": "user", "content": [{"type": "text", "text": "look"}, {"type": "image_upload", "upload_id": upload_id}]}]},
            headers=headers_a,
        )
        assert r.status_code == 200, r.text

        # user B cannot reference A's upload: owner-bound, and indistinguishable
        # from an unknown id (no existence leak)
        r = await client_b.post(
            "/api/chat/completions",
            json={"messages": [{"role": "user", "content": [{"type": "image_upload", "upload_id": upload_id}]}]},
            headers=headers_b,
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_expired_upload_reference_is_410(harness):
    client, session_local, ids = harness
    headers = await _login(client, USER_A["email"], USER_A["password"])
    async with session_local() as db:
        db.add(
            ChatUpload(
                user_id=ids["user_a"].id,
                bytes=png_bytes(2, 2),
                mime="image/png",
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await db.commit()
        upload_id = str((await db.execute(select(ChatUpload))).scalars().first().id)
    r = await client.post(
        "/api/chat/completions",
        json={"messages": [{"role": "user", "content": [{"type": "image_upload", "upload_id": upload_id}]}]},
        headers=headers,
    )
    assert r.status_code == 410
    assert "expired" in r.json()["detail"]


@pytest.mark.asyncio
async def test_vision_unsupported_chain_gets_a_clear_message(monkeypatch, harness):
    client, _session_local, _ids = harness
    headers = await _login(client, USER_A["email"], USER_A["password"])
    r = await client.post("/api/chat/uploads", files={"file": ("cat.png", png_bytes(), "image/png")}, headers=headers)
    upload_id = r.json()["upload_id"]

    class _S:
        openai_api_key = "test-key"

        def model_chain(self):
            return ["gpt-3.5-turbo"]  # known text-only family

    import routes.chat as chat_mod

    monkeypatch.setattr(chat_mod, "get_settings", lambda: _S())
    r = await client.post(
        "/api/chat/completions",
        json={"messages": [{"role": "user", "content": [{"type": "image_upload", "upload_id": upload_id}]}]},
        headers=headers,
    )
    assert r.status_code == 400
    assert "does not support image input" in r.json()["content"]


@pytest.mark.asyncio
async def test_upload_purges_expired_rows(harness):
    client, session_local, ids = harness
    headers = await _login(client, USER_A["email"], USER_A["password"])
    async with session_local() as db:
        db.add(
            ChatUpload(
                user_id=ids["user_a"].id,
                bytes=PNG_MAGIC + b"old",
                mime="image/png",
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await db.commit()
    r = await client.post("/api/chat/uploads", files={"file": ("cat.png", png_bytes(), "image/png")}, headers=headers)
    assert r.status_code == 200
    async with session_local() as db:
        rows = (await db.execute(select(ChatUpload))).scalars().all()
        assert rows, "the fresh upload is stored"
        assert all((row.expires_at.replace(tzinfo=UTC) if row.expires_at.tzinfo is None else row.expires_at) > datetime.now(UTC) for row in rows), "expired rows are purged with the upload"
