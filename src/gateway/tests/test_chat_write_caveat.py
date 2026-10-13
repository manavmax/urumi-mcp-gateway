"""A turn that dies after a write already succeeded must say so (ADR-031).

The live bug: a member asked the assistant to "create a note titled test, then list my
notes". `notes__create_note` succeeded, then the model chain gave up and the turn ended
with a bare "AI models are busy ...". Nothing told the user their note HAD been created,
so an obvious retry would create a second one - and nothing was rolled back.

`chat_loop` therefore remembers the write tools that succeeded during the turn and, if
the turn then ends early, says exactly what changed: "<tool> already succeeded, so
nothing was rolled back - a retry may repeat it. Check the store before you retry."

Read-only tools (`list_*`, `get_*`) must never trigger that note, otherwise every failed
turn after a lookup would cry wolf.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import chat.llm_fallback as fb
import pytest

TOOLS = [
    {"name": "notes__create_note", "description": "Create a note.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "notes__list_notes", "description": "List notes.", "inputSchema": {"type": "object", "properties": {}}},
]

CHAIN = ["gemini-a", "gemini-b"]


class StatusBusy(Exception):
    """Stand-in for openai.APIStatusError: 503 high demand."""

    status_code = 503


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
    """Answers the server_id lookup chat_loop does for the audit row."""

    async def execute(self, stmt):
        class _Res:
            def scalar_one_or_none(self):
                return "00000000-0000-0000-0000-00000000000a"

        return _Res()

    async def commit(self):
        pass


async def _allowed(_db):
    return TOOLS


async def _route_ok(db, name, arguments):
    return {"tool": name, "args": arguments, "id": "note-1", "title": "test"}


async def _audit(**_kwargs):
    return None


def _tool_call_response(name: str, call_id: str = "call_1"):
    msg = SimpleNamespace(content="", tool_calls=[
        SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments="{}"))
    ])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


async def _run_turn(monkeypatch, tool_name: str, request_id: str):
    """One turn: step 1 asks for `tool_name`, every later LLM call is busy."""
    import audit.queue as audit_queue
    import gw_mcp.router as gw_router
    import openai
    from chat import agent

    monkeypatch.setattr(agent, "get_settings", lambda: _Settings())
    monkeypatch.setattr(agent, "_get_allowed_tools", _allowed)
    monkeypatch.setattr(gw_router, "call_tool_routed", _route_ok)
    monkeypatch.setattr(audit_queue, "log_audit", _audit)

    state = {"n": 0}

    async def create(**kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return _tool_call_response(tool_name)
        raise StatusBusy()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeOpenAI)

    user = SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
    events = []
    async for evt in agent.chat_loop(_DB(), user, [{"role": "user", "content": "go"}], request_id):
        events.append(evt)
    return events


def _text_of(events) -> str:
    return " ".join(e.get("content", "") for e in events if e.get("type") in ("token", "text"))


@pytest.mark.parametrize("name,expected", [
    ("notes__create_note", True),
    ("woo__create_product", True),
    ("notes__delete_note", True),
    ("woo__update_order", True),
    ("notes__list_notes", False),
    ("woo__list_products", False),
    ("time__get_current_time", False),
    ("woo__get_order", False),
    ("create_note_without_prefix", True),
])
def test_is_write_tool_detects_write_verbs(name, expected):
    from chat.agent import _is_write_tool

    assert _is_write_tool(name) is expected


def test_turn_ending_after_a_write_names_it_and_says_nothing_was_rolled_back(monkeypatch):
    """The live scenario: the write succeeds, then no model is left to finish the turn."""
    events = asyncio.run(_run_turn(monkeypatch, "notes__create_note", "req-write-1"))
    text = _text_of(events)

    assert "AI models are busy" in text  # the category is still named first
    assert "notes__create_note already succeeded" in text
    assert "nothing was rolled back" in text
    assert "retry may repeat it" in text
    tool_events = [e for e in events if e.get("type") == "tool_call"]
    assert [e["tool"] for e in tool_events] == ["notes__create_note"]
    assert all(e["outcome"] == "success" for e in tool_events)
    # machine-readable, so the dashboard can render it as a proper warning
    assert [e.get("writes") for e in events if e.get("type") == "text"] == [["notes__create_note"]]


def test_turn_ending_after_a_read_does_not_warn_about_writes(monkeypatch):
    events = asyncio.run(_run_turn(monkeypatch, "notes__list_notes", "req-read-1"))
    text = _text_of(events)

    assert "AI models are busy" in text
    assert "already succeeded" not in text
    assert "rolled back" not in text
    assert not [e for e in events if e.get("type") == "text" and e.get("writes")]


def test_a_failed_write_is_not_reported_as_succeeded(monkeypatch):
    """An upstream_error write must NOT get the "nothing was rolled back" note."""
    events = asyncio.run(_run_turn_with_failing_route(monkeypatch))
    text = _text_of(events)
    outcomes = [e.get("outcome") for e in events if e.get("type") == "tool_call"]
    assert outcomes  # the write was attempted
    assert all(o == "upstream_error" for o in outcomes)  # and never succeeded
    assert "already succeeded" not in text
    assert "rolled back" not in text


async def _run_turn_with_failing_route(monkeypatch):
    import audit.queue as audit_queue
    import gw_mcp.router as gw_router
    import openai
    from chat import agent

    monkeypatch.setattr(agent, "get_settings", lambda: _Settings())
    monkeypatch.setattr(agent, "_get_allowed_tools", _allowed)
    monkeypatch.setattr(audit_queue, "log_audit", _audit)

    async def _route_fail(db, name, arguments):
        raise RuntimeError("notes upstream exploded")

    monkeypatch.setattr(gw_router, "call_tool_routed", _route_fail)

    async def create(**kwargs):
        return _tool_call_response("notes__create_note")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeOpenAI)

    user = SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
    events = []
    async for evt in agent.chat_loop(_DB(), user, [{"role": "user", "content": "go"}], "req-write-fail-1"):
        events.append(evt)
    return events
