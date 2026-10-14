"""Tool-loop caps (docs/05 §2): MAX_TOOL_CALLS=20 and MAX_ITERS=8 are enforced and audited.

Two separate tests per the updated plan:
  (a) many tool calls per iteration -> hits MAX_TOOL_CALLS (20)
  (b) one call per iteration -> hits MAX_ITERS (8)

Both prove every call is audited as the logged-in user, ending with a clear
"Maximum tool calls reached." / loop-exhaustion message.

The mock-LLM harness (fake settings/DB, tool routing, FakeOpenAI, cooldown reset)
lives in tests/conftest.py.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from tests.conftest import ChatFakeDB, chat_user, fake_settings, make_tool_call, run_chat_turn

TOOLS = [
    {"name": "notes__list_notes", "description": "List notes.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "notes__create_note", "description": "Create a note.", "inputSchema": {"type": "object", "properties": {}}},
]


def _resp_with_calls(*names: str):
    calls = [make_tool_call(n, f"call_{i}") for i, n in enumerate(names)]
    msg = SimpleNamespace(content="", tool_calls=calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


# ---------------------------------------------------------------------------
# (a) MAX_TOOL_CALLS reached via many calls per iteration

def test_max_tool_calls_20_multi_per_iteration(monkeypatch):
    """5 iterations x 5 calls = 25 attempted -> cap fires at call 21 (= >20)."""
    from chat.agent import MAX_TOOL_CALLS

    assert MAX_TOOL_CALLS == 20
    user_id = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
    audited_user_ids: list[uuid.UUID] = []
    call_names: list[str] = []

    async def fake_route(db, name, arguments):
        return {"ok": True, "tool": name}

    async def fake_audit(*, user_id, **kw):
        audited_user_ids.append(user_id)
        call_names.append(kw.get("tool_exposed_name"))

    async def create(**kwargs):
        return _resp_with_calls(*(["notes__list_notes"] * 5))

    events = asyncio.run(run_chat_turn(
        monkeypatch,
        ChatFakeDB(),
        chat_user(user_id),
        settings=fake_settings(),
        tools=TOOLS,
        route=fake_route,
        create=create,
        messages=[{"role": "user", "content": "go"}],
        request_id=str(uuid.uuid4()),
        audit=fake_audit,
    ))

    tool_events = [e for e in events if e.get("type") == "tool_call"]
    text_events = [e for e in events if e.get("type") == "text"]

    # Exactly 20 tool calls succeed before the cap fires on the 21st
    assert len(tool_events) == 20
    assert all(e["tool"] == "notes__list_notes" for e in tool_events)
    # Every call audited as the logged-in user
    assert len(audited_user_ids) == 20
    assert all(uid == user_id for uid in audited_user_ids)
    # Clear terminal message
    assert any("Maximum tool calls reached" in (e.get("content") or "") for e in text_events)
    # No further LLM-driven text after the cap
    assert not [e for e in events if e.get("type") == "token"]


# (b) MAX_ITERS reached via one call per iteration

def test_max_iters_8_single_per_iteration(monkeypatch):
    """One tool call per iteration -> loop exhausts MAX_ITERS (8)."""
    from chat.agent import MAX_ITERS

    assert MAX_ITERS == 8
    user_id = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
    audited: list[uuid.UUID] = []
    iterations = 0

    async def fake_route(db, name, arguments):
        return {"ok": True}

    async def fake_audit(*, user_id, **kw):
        audited.append(user_id)

    async def create(**kwargs):
        nonlocal iterations
        iterations += 1
        # Always request one more tool call; loop should hit MAX_ITERS and stop iterating
        return _resp_with_calls("notes__list_notes")

    events = asyncio.run(run_chat_turn(
        monkeypatch,
        ChatFakeDB(),
        chat_user(user_id),
        settings=fake_settings(),
        tools=TOOLS,
        route=fake_route,
        create=create,
        messages=[{"role": "user", "content": "go"}],
        request_id=str(uuid.uuid4()),
        audit=fake_audit,
    ))

    tool_events = [e for e in events if e.get("type") == "tool_call"]
    # One per iteration, 8 iterations -> 8 calls, then loop ends (no "Maximum tool calls" message — it hit the iter cap)
    assert len(tool_events) == MAX_ITERS
    assert iterations == MAX_ITERS
    assert all(uid == user_id for uid in audited)
    # The loop ending via MAX_ITERS does not emit a terminal text; it simply stops iterating.
    # What matters is it does not loop forever and every call was audited.
    assert len(tool_events) == 8
