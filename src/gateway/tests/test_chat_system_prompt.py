"""FIX PASS F1-8: the chat system prompt carries the user's local date/time.

build_system_prompt(tz) stamps the validated IANA zone into the prompt so
"today" means the user's today; an unknown zone falls back to no stamp (and
the route itself falls back the same way). The prompt also pins the order-list
table format (Order, Status, Total, Placed, Items).
"""

from __future__ import annotations

import re

import pytest
from chat.agent import SYSTEM_PROMPT, build_system_prompt


def test_prompt_keeps_injection_boundary():
    assert "untrusted" in SYSTEM_PROMPT
    assert "per-turn JSON envelope" in SYSTEM_PROMPT


def test_prompt_pins_order_table_format():
    p = build_system_prompt(None)
    assert "Order, Status, Total, Placed, Items" in p
    assert "15 Oct, 11:01 PM" in p, "human date example missing"
    assert "draft" in p.lower(), "draft exclusion missing"


def test_valid_tz_stamps_local_time():
    p = build_system_prompt("Europe/Berlin")
    assert "Europe/Berlin" in p
    # the stamp must be a real date line the model can rely on
    assert "local time is" in p


def test_invalid_tz_falls_back_cleanly():
    assert "Bogus/Zone" not in build_system_prompt("Bogus/Zone")
    assert "local time" not in build_system_prompt(None), "no tz must not invent one"
    # and it still carries the base rules
    assert "Order, Status, Total, Placed, Items" in build_system_prompt("No/Such-Zone")


@pytest.mark.parametrize("tz", ["UTC", "Asia/Kolkata", "America/Los_Angeles", "Europe/Paris"])
def test_known_zones_produce_a_stamp(tz):
    p = build_system_prompt(tz)
    assert tz in p
    assert "Today" in p


@pytest.mark.asyncio
async def test_route_accepts_tz_field(monkeypatch):
    """The route accepts tz in the body (200) and validates it before use."""
    import contextlib
    from types import SimpleNamespace

    import httpx
    from auth.rbac import hash_password
    from db.models import Base, User
    from db.session import get_db
    from httpx import ASGITransport
    from main import create_app
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

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
        db.add(User(email="tz-admin@urumi.local", password_hash=await hash_password("tz-pass-123"), role="admin"))
        await db.commit()

    import routes.chat as chat_route

    monkeypatch.setattr(chat_route, "get_settings", lambda: SimpleNamespace(openai_api_key=""))

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/auth/login", json={"email": "tz-admin@urumi.local", "password": "tz-pass-123"})
        assert r.status_code == 200, r.text
        headers = {"X-CSRF-Token": r.json()["csrf_token"]}
        for payload in (
            {"messages": [{"role": "user", "content": "hi"}], "tz": "Europe/Berlin"},
            {"messages": [{"role": "user", "content": "hi"}]},
            {"messages": [{"role": "user", "content": "hi"}], "tz": "Not/AZone"},
        ):
            r = await client_post(c, headers, payload)
            assert r.status_code == 200, f"{payload} -> {r.status_code} {r.text}"

    await engine.dispose()


async def client_post(client, headers, payload):
    return await client.post("/api/chat/completions", headers=headers, json=payload)
