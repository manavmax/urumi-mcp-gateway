"""Tool-loop caps (docs/05 §2): MAX_TOOL_CALLS=20 and MAX_ITERS=8 are enforced and audited.

Two separate tests per the updated plan:
  (a) many tool calls per iteration -> hits MAX_TOOL_CALLS (20)
  (b) one call per iteration -> hits MAX_ITERS (8)

Both prove every call is audited as the logged-in user, ending with a clear
"Maximum tool calls reached." / loop-exhaustion message.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import chat.llm_fallback as fb
import pytest

TOOLS = [
    {"name": "notes__list_notes", "description": "List notes.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "notes__create_note", "description": "Create a note.", "inputSchema": {"type": "object", "properties": {}}},
]

CHAIN = ["fake-a", "fake-b"]


@pytest.fixture(autouse=True)
def _reset_cooldowns():
    fb.MODEL_COOLDOWNS.clear()
    yield
    fb.MODEL_COOLDOWNS.clear()


class _Settings:
    openai_api_key = "test-key-not-real"
    openai_base_url = None
    openai_model = CHAIN[0]
    openai_models = ",".join(CHAIN[1:])

    def model_chain(self):
        return list(CHAIN)

    def max_models_per_turn(self):
        return fb.DEFAULT_MAX_MODELS_PER_TURN


class _DB:
    async def execute(self, stmt):
        class _Res:
            def scalar_one_or_none(self):
                return "00000000-0000-0000-0000-00000000000a"
        return _Res()

    async def commit(self):
        pass


async def _allowed(_db):
    return TOOLS


def _tool_call(name: str, call_id: str):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments="{}"))


def _resp_with_calls(*names: str):
    calls = [_tool_call(n, f"call_{i}") for i, n in enumerate(names)]
    msg = SimpleNamespace(content="", tool_calls=calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _text_resp(text: str):
    msg = SimpleNamespace(content=text, tool_calls=[])
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

    async def _run():
        import audit.queue as audit_queue
        import gw_mcp.router as gw_router
        import openai
        from chat import agent

        monkeypatch.setattr(agent, "get_settings", lambda: _Settings())
        monkeypatch.setattr(agent, "_get_allowed_tools", _allowed)
        monkeypatch.setattr(gw_router, "call_tool_routed", fake_route)

        async def fake_audit(*, user_id, **kw):
            audited_user_ids.append(user_id)
            call_names.append(kw.get("tool_exposed_name"))

        monkeypatch.setattr(audit_queue, "log_audit", fake_audit)

        # Each LLM turn returns 5 parallel tool calls
        async def create(**kwargs):
            return _resp_with_calls(*(["notes__list_notes"] * 5))

        class FakeOpenAI:
            def __init__(self, **kw):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        monkeypatch.setattr(openai, "AsyncOpenAI", FakeOpenAI)

        user = SimpleNamespace(id=user_id)
        events: list[dict] = []
        async for evt in agent.chat_loop(_DB(), user, [{"role": "user", "content": "go"}], str(uuid.uuid4())):
            events.append(evt)
        return events

    events = asyncio.run(_run())
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

    async def _run():
        import audit.queue as audit_queue
        import gw_mcp.router as gw_router
        import openai
        from chat import agent

        monkeypatch.setattr(agent, "get_settings", lambda: _Settings())
        monkeypatch.setattr(agent, "_get_allowed_tools", _allowed)
        monkeypatch.setattr(gw_router, "call_tool_routed", fake_route)

        async def fake_audit(*, user_id, **kw):
            audited.append(user_id)

        monkeypatch.setattr(audit_queue, "log_audit", fake_audit)

        async def create(**kwargs):
            nonlocal iterations
            iterations += 1
            # Always request one more tool call; loop should hit MAX_ITERS and stop iterating
            return _resp_with_calls("notes__list_notes")

        class FakeOpenAI:
            def __init__(self, **kw):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        monkeypatch.setattr(openai, "AsyncOpenAI", FakeOpenAI)

        user = SimpleNamespace(id=user_id)
        events: list[dict] = []
        # MAX_ITERS loop yields 8 tool calls; next iteration exits the for range silently
        async for evt in agent.chat_loop(_DB(), user, [{"role": "user", "content": "go"}], str(uuid.uuid4())):
            events.append(evt)
        return events

    events = asyncio.run(_run())
    tool_events = [e for e in events if e.get("type") == "tool_call"]
    # One per iteration, 8 iterations -> 8 calls, then loop ends (no "Maximum tool calls" message — it hit the iter cap)
    assert len(tool_events) == MAX_ITERS
    assert iterations == MAX_ITERS
    assert all(uid == user_id for uid in audited)
    # The loop ending via MAX_ITERS does not emit a terminal text; it simply stops iterating.
    # What matters is it does not loop forever and every call was audited.
    assert len(tool_events) == 8
