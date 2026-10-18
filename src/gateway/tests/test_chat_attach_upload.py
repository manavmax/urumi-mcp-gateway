"""chat__attach_product_image through the REAL chat_loop (F3, ADR-035).

Real sqlite DB (users + chat_uploads + tool_permissions + audit), fake LLM, fake
upstream route. Pinned here:
  - the helper is only offered to the model when woo__add_product_image is allowed
  - success: the bytes are routed through woo__add_product_image (the normal
    routing path, so permissions and audit apply), the upload row is deleted
    after ONE use, the audit row is written and contains no image bytes, and the
    model never sees base64
  - another user's upload id -> validation_error, row untouched, nothing routed
  - an expired upload -> a clear validation error
  - a member whose role denies woo__add_product_image gets permission_denied +
    an audit row, and the helper is not even offered to the model
  - a turn that dies after a successful attach names woo__add_product_image in
    the "nothing was rolled back" caveat (ADR-031 semantics for the helper)
"""

from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from auth.rbac import hash_password
from db.models import Base, ChatUpload, Server, ToolPermission, User
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from tests.conftest import (
    fake_settings,
    install_fake_openai,
    patch_chat_agent,
    text_response,
)

USER = {"email": "member-a@urumi.local", "password": "member-a-pass-123"}
OTHER = {"email": "member-b@urumi.local", "password": "member-b-pass-123"}

TOOLS = [
    {"name": "woo__add_product_image", "description": "Add an image to a product.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "woo__list_product_images", "description": "List product images.", "inputSchema": {"type": "object", "properties": {}}},
]

CHAT_ATTACH_TOOL_NAME = "chat__attach_product_image"


def png_bytes(w: int = 2, h: int = 2) -> bytes:
    img = Image.new("RGBA", (w, h), (200, 30, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def tool_call_args(name: str, args: dict, call_id: str = "call_1"):
    """OpenAI-shaped response whose message asks for ONE tool call with arguments."""
    tc = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    msg = SimpleNamespace(content="", tool_calls=[tc])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def text_msg(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=[]))])


def fake_image_response(image_id=9, url="https://store.invalid/u.png") -> dict:
    """The shape call_tool_routed returns for a successful woo tool call."""
    return {
        "content": [{"type": "text", "text": json.dumps({"attached": True, "image_id": image_id, "url": url})}],
        "isError": False,
    }


class StatusBusy(Exception):
    """Stand-in for openai.APIStatusError: 503 high demand (as in the caveat tests)."""

    status_code = 503


@pytest.fixture()
async def harness():
    """Real sqlite DB with two members + the woo server row (no live upstream)."""
    from tests.conftest import sqlite_ready_metadata

    sqlite_ready_metadata()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as db:
        member = User(email=USER["email"], password_hash=await hash_password(USER["password"]), role="member")
        other = User(email=OTHER["email"], password_hash=await hash_password(OTHER["password"]), role="member")
        db.add_all([member, other])
        await db.flush()
        db.add(Server(slug="woo", url="http://woo.invalid:8000/mcp", auth_type="none", timeout_ms=5000))
        await db.commit()

    yield SessionLocal, {"member": member, "other": other}
    await engine.dispose()


async def _upload_row(SessionLocal, user_id, *, expired: bool = False) -> str:
    async with SessionLocal() as db:
        now = datetime.now(UTC)
        row = ChatUpload(
            user_id=user_id,
            bytes=png_bytes(2, 2),
            mime="image/png",
            created_at=now,
            expires_at=now + (timedelta(seconds=-1) if expired else timedelta(minutes=10)),
        )
        db.add(row)
        await db.commit()
        return str(row.id)


async def _drive(monkeypatch, db, user, *, tools, create, route, audit=None, messages=None):
    """Patch the agent collaborators and drive one chat_loop turn to completion."""
    from chat import agent as agent_mod

    async def noop_audit(**_kwargs):
        return None

    patch_chat_agent(
        monkeypatch,
        settings=fake_settings(),
        tools=tools,
        route=route,
        audit=audit if audit is not None else noop_audit,
    )
    install_fake_openai(monkeypatch, create)
    events: list[dict] = []
    async for evt in agent_mod.chat_loop(db, user, messages or [{"role": "user", "content": "attach it"}], "req-attach"):
        events.append(evt)
    return events


@pytest.mark.asyncio
async def test_helper_only_offered_when_add_product_image_allowed(monkeypatch, harness):
    session_local, users = harness

    seen_names: list[list[str]] = []

    async def create(**kwargs):
        seen_names.append([t["function"]["name"] for t in (kwargs.get("tools") or [])])
        return text_response("ok")

    async def route(db, name, arguments):  # pragma: no cover - never called here
        return fake_image_response()

    async with session_local() as db:
        await _drive(monkeypatch, db, users["member"], tools=TOOLS, create=create, route=route)
    assert "chat__attach_product_image" in seen_names[0]

    async with session_local() as db:
        db.add(ToolPermission(role="member", server_slug="woo", tool_name="woo__add_product_image"))
        await db.commit()
    async with session_local() as db:
        seen_names.clear()
        await _drive(monkeypatch, db, users["member"], tools=TOOLS, create=create, route=route)
    assert "chat__attach_product_image" not in seen_names[0]


@pytest.mark.asyncio
async def test_attach_success_deletes_row_and_audits_without_bytes(monkeypatch, harness):
    session_local, users = harness
    member = users["member"]
    upload_id = await _upload_row(session_local, member.id)
    b64 = base64.b64encode(png_bytes()).decode()

    routed: list[tuple] = []
    audit_calls: list[dict] = []
    state = {"n": 0}

    async def route(db, name, arguments):
        routed.append((name, dict(arguments or {})))
        return fake_image_response()

    async def audit(**kwargs):
        audit_calls.append(dict(kwargs))

    async def create(**kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return tool_call_args(CHAT_ATTACH_TOOL_NAME, {"upload_id": upload_id, "product_id": 7})
        return text_response("attached to product 7")

    async with session_local() as db:
        events = await _drive(monkeypatch, db, member, tools=TOOLS, create=create, route=route, audit=audit)

    # routed through the NORMAL path under the woo tool's name
    assert routed and routed[0][0] == "woo__add_product_image"
    assert routed[0][1]["product_id"] == 7
    assert base64.b64decode(routed[0][1]["image_base64"])[:8] == b"\x89PNG\r\n\x1a\n"
    # the model never sees base64: the tool event carries no bytes
    tool_evt = next(e for e in events if e.get("type") == "tool_call")
    assert tool_evt["outcome"] == "success"
    assert b64 not in json.dumps(tool_evt, default=str)
    # the audit row is the real tool call, with no bytes anywhere in it
    assert audit_calls, "the attach wrote an audit row"
    assert audit_calls[0]["tool_exposed_name"] == "woo__add_product_image"
    assert audit_calls[0]["outcome"] == "success"
    assert b64 not in json.dumps(audit_calls, default=str)
    # one-shot use: the row is gone
    async with session_local() as db:
        remaining = (await db.execute(select(ChatUpload))).scalars().all()
        assert remaining == [], "the upload row is deleted after a successful attach"


@pytest.mark.asyncio
async def test_attach_rejects_another_users_upload(monkeypatch, harness):
    session_local, users = harness
    other_upload_id = await _upload_row(session_local, users["other"].id)

    routed: list[tuple] = []
    state = {"n": 0}

    async def route(db, name, arguments):
        routed.append((name, dict(arguments or {})))
        return fake_image_response()

    async def create(**kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return tool_call_args(CHAT_ATTACH_TOOL_NAME, {"upload_id": other_upload_id, "product_id": 7})
        return text_msg("done")

    async with session_local() as db:
        events = await _drive(monkeypatch, db, users["member"], tools=TOOLS, create=create, route=route)

    tool_evts = [e for e in events if e.get("type") == "tool_call"]
    assert tool_evts and tool_evts[0]["outcome"] == "validation_error"
    assert "private" in tool_evts[0]["output"]["error"]
    assert routed == [], "nothing was routed upstream for someone else's upload"
    async with session_local() as db:
        row = (await db.execute(select(ChatUpload))).scalars().first()
        assert row is not None, "another user's row is untouched"


@pytest.mark.asyncio
async def test_attach_rejects_expired_upload(monkeypatch, harness):
    session_local, users = harness
    upload_id = await _upload_row(session_local, users["member"].id, expired=True)

    routed: list[tuple] = []
    state = {"n": 0}

    async def route(db, name, arguments):
        routed.append((name, dict(arguments or {})))
        return fake_image_response()

    async def create(**kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return tool_call_args(CHAT_ATTACH_TOOL_NAME, {"upload_id": upload_id, "product_id": 7})
        return text_response("done")

    async with session_local() as db:
        events = await _drive(monkeypatch, db, users["member"], tools=TOOLS, create=create, route=route)

    tool_evts = [e for e in events if e.get("type") == "tool_call"]
    assert tool_evts and tool_evts[0]["outcome"] == "validation_error"
    assert "expired" in tool_evts[0]["output"]["error"]
    assert routed == []


@pytest.mark.asyncio
async def test_member_without_access_gets_permission_denied(monkeypatch, harness):
    session_local, users = harness
    member = users["member"]
    upload_id = await _upload_row(session_local, member.id)
    async with session_local() as db:
        db.add(ToolPermission(role="member", server_slug="woo", tool_name="woo__add_product_image"))
        await db.commit()

    routed: list[tuple] = []
    audit_calls: list[dict] = []

    async def route(db, name, arguments):
        routed.append((name, dict(arguments or {})))
        return fake_image_response()

    async def audit(**kwargs):
        audit_calls.append(dict(kwargs))

    state = {"n": 0}

    async def create(**kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return tool_call_args(CHAT_ATTACH_TOOL_NAME, {"upload_id": upload_id, "product_id": 7})
        return text_msg("denied, as expected")

    async with session_local() as db:
        events = await _drive(monkeypatch, db, member, tools=TOOLS, create=create, route=route, audit=audit)

    tool_evts = [e for e in events if e.get("type") == "tool_call"]
    assert tool_evts[0]["outcome"] == "permission_denied"
    assert routed == [], "a denied member never reaches the upstream"
    assert any(a.get("outcome") == "permission_denied" for a in audit_calls), "the denial is audited"
    async with session_local() as db:
        row = (await db.execute(select(ChatUpload))).scalars().first()
        assert row is not None, "the row survives a denied attach"


@pytest.mark.asyncio
async def test_turn_dying_after_attach_names_woo_add_product_image(monkeypatch, harness):
    """ADR-031 for the helper: the CAVEAT names the real write, not the helper shell."""
    session_local, users = harness
    member = users["member"]
    upload_id = await _upload_row(session_local, member.id)

    state = {"n": 0}

    async def route(db, name, arguments):
        return fake_image_response()

    async def create(**kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return tool_call_args(CHAT_ATTACH_TOOL_NAME, {"upload_id": upload_id, "product_id": 7})
        raise StatusBusy()

    async with session_local() as db:
        events = await _drive(monkeypatch, db, member, tools=TOOLS, create=create, route=route)

    final = [e for e in events if e.get("type") == "text"][-1]
    assert "woo__add_product_image already succeeded" in final["content"]
    async with session_local() as db:
        remaining = (await db.execute(select(ChatUpload))).scalars().all()
        assert remaining == [], "the successful attach already consumed the row"
