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

The mock-LLM harness (fake settings/DB, tool routing, FakeOpenAI, cooldown reset)
lives in tests/conftest.py.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.conftest import ChatFakeDB, chat_user, fake_settings, run_chat_turn, tool_call_response

TOOLS = [
    {"name": "notes__create_note", "description": "Create a note.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "notes__list_notes", "description": "List notes.", "inputSchema": {"type": "object", "properties": {}}},
]


class StatusBusy(Exception):
    """Stand-in for openai.APIStatusError: 503 high demand."""

    status_code = 503


async def _route_ok(db, name, arguments):
    return {"tool": name, "args": arguments, "id": "note-1", "title": "test"}


async def _run_turn(monkeypatch, tool_name: str, request_id: str):
    """One turn: step 1 asks for `tool_name`, every later LLM call is busy."""
    state = {"n": 0}

    async def create(**kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return tool_call_response(tool_name)
        raise StatusBusy()

    return await run_chat_turn(
        monkeypatch,
        ChatFakeDB(),
        chat_user(),
        settings=fake_settings(),
        tools=TOOLS,
        route=_route_ok,
        create=create,
        messages=[{"role": "user", "content": "go"}],
        request_id=request_id,
    )


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
    async def _route_fail(db, name, arguments):
        raise RuntimeError("notes upstream exploded")

    async def create(**kwargs):
        return tool_call_response("notes__create_note")

    return await run_chat_turn(
        monkeypatch,
        ChatFakeDB(),
        chat_user(),
        settings=fake_settings(),
        tools=TOOLS,
        route=_route_fail,
        create=create,
        messages=[{"role": "user", "content": "go"}],
        request_id="req-write-fail-1",
    )
