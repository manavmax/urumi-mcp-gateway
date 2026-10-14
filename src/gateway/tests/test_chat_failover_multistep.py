"""Forced failover across a MULTI-STEP tool loop (docs/DECISIONS.md ADR-029 + ADR-030).

What the single-call fallback tests cannot show: when the top of the chain dies *during*
a tool loop, the turn must still finish on the next model, and the model that produced
the echoed tool_calls must not have its Gemini `thought_signature` handed to a different
model.

The switch is TEST-ONLY and lives here, never in production code:

    URUMI_TEST_FORCE_TOP_MODEL_503=1      top model returns 503 on EVERY call (forced
                                          failover; this is the default)
    URUMI_TEST_FORCE_TOP_MODEL_503=0      top model serves normally (control run)

Run it with visible output:

    cd src/gateway && ../../.venv/bin/python -m pytest tests/test_chat_failover_multistep.py -s -q
"""

from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import chat.llm_fallback as fb

from tests.conftest import ChatFakeDB, chat_user, fake_settings, make_tool_call, run_chat_turn

CHAIN = ["gemini-top", "gemini-next", "gemini-third"]
TOP, NEXT = CHAIN[0], CHAIN[1]  # the third entry proves the failover does NOT walk the chain

TOOLS = [
    {"name": "woo__list_products", "description": "List products.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "woo__list_orders", "description": "List orders.", "inputSchema": {"type": "object", "properties": {}}},
]


class StatusError(Exception):
    """Minimal stand-in for openai.APIStatusError carrying an HTTP status."""

    def __init__(self, status: int, message: str = ""):
        super().__init__(message or f"http {status}")
        self.status_code = status


class FakeResp:
    def __init__(self, content: str = "ok", tool_calls=None):
        msg = SimpleNamespace(content=content, tool_calls=tool_calls or [])
        self.choices = [SimpleNamespace(message=msg)]


async def _fake_route(db, name, arguments):
    # deterministic per tool, so the raw output shows the loop really iterated
    return {"tool": name, "args": arguments, "rows": [{"id": 1}, {"id": 2}]}


async def _fake_audit(**_kwargs):
    return None


def _switch_on() -> bool:
    """Read the test-only switch at call time (so a test can set it per run)."""
    return os.environ.get("URUMI_TEST_FORCE_TOP_MODEL_503", "1") not in ("0", "false", "no")


async def _multi_step_loop(monkeypatch):
    """Drive chat_loop over a 3-step turn: 2 tool calls, then the final answer."""
    force_503 = _switch_on()
    calls: list[dict] = []
    next_steps = {"n": 0}

    def next_behavior(_kw):
        # the model that serves the loop: step 1 -> tool call, step 2 -> tool call, step 3 -> answer
        next_steps["n"] += 1
        if next_steps["n"] == 1:
            return FakeResp(content="", tool_calls=[make_tool_call("woo__list_products", "call_1", "sig-NEXT")])
        if next_steps["n"] == 2:
            return FakeResp(content="", tool_calls=[make_tool_call("woo__list_orders", "call_2")])
        return FakeResp("found 2 products and 0 orders")

    async def create(**kwargs):
        model = kwargs["model"]
        # snapshot: chat_loop appends to the same list, so a live reference would show
        # every call the whole final history
        entry = {"model": model, "outcome": "200", "messages": [dict(m) for m in (kwargs.get("messages") or [])]}
        calls.append(entry)
        if model == TOP:
            if force_503:
                entry["outcome"] = "503"
                raise StatusError(503, "This model is currently experiencing high demand")
            return next_behavior(kwargs)
        if model == NEXT:
            return next_behavior(kwargs)
        raise StatusError(503, "unexpected fallback past the healthy model")

    return await run_chat_turn(
        monkeypatch,
        ChatFakeDB(),
        chat_user(),
        settings=fake_settings(CHAIN),
        tools=TOOLS,
        route=_fake_route,
        create=create,
        messages=[{"role": "user", "content": "what do we sell?"}],
        request_id="req-multistep-1",
    ), calls


def _show(events, calls):
    """Raw output: exactly what the SSE stream carries for the turn."""
    on = _switch_on()
    print(f"switch URUMI_TEST_FORCE_TOP_MODEL_503={'1' if on else '0'} -> "
          f"top model {'returns 503 on every call' if on else 'serves normally'}")
    print("llm attempts: " + " -> ".join(f"{c['model']}({c['outcome']})" for c in calls))
    for evt in events:
        print(f"event: {json.dumps(evt, default=str)}")
    print("event: [DONE]")


def test_forced_failover_completes_a_multi_step_tool_loop(monkeypatch):
    """With the switch ON (default) the top model returns 503 on EVERY call, so the whole
    multi-step loop has to complete on the next model of the chain."""
    monkeypatch.setenv("URUMI_TEST_FORCE_TOP_MODEL_503", "1")
    events, calls = asyncio.run(_multi_step_loop(monkeypatch))
    _show(events, calls)

    served = [e["model"] for e in events if e.get("type") == "model"]
    tool_events = [e for e in events if e.get("type") == "tool_call"]
    text = " ".join(e.get("content", "") for e in events if e.get("type") in ("token", "text"))

    # the top model is dead for the WHOLE turn; every step is served by the next one
    assert served == [NEXT, NEXT, NEXT]
    top_calls = [c for c in calls if c["model"] == TOP]
    assert len(top_calls) == 1  # asked once, then cooled down - never re-hit mid-turn
    # the 503 hit on the FIRST call: it was asked before any tool result existed, so the
    # failover carried the same conversation forward on a different model
    assert not [m for m in top_calls[0]["messages"] if m.get("role") == "tool"]
    # and the serving model keeps its own thought_signature when it continues the turn
    # (stripping applies only when a DIFFERENT model takes over - covered in
    # test_llm_fallback.py)
    for c in [c for c in calls if c["model"] == NEXT][1:]:
        echoed = [tc for m in c["messages"] for tc in m.get("tool_calls", [])]
        assert any("extra_content" in tc for tc in echoed)
    assert fb.MODEL_COOLDOWNS.get(TOP, 0) > 0

    _assert_loop_completed(events, tool_events, text)


def test_top_model_serves_the_loop_when_the_switch_is_off(monkeypatch):
    """Same loop, control run: URUMI_TEST_FORCE_TOP_MODEL_503=0 disables the forced 503,
    so the test proves the assertion above is about the failover and not about the mock."""
    monkeypatch.setenv("URUMI_TEST_FORCE_TOP_MODEL_503", "0")
    events, calls = asyncio.run(_multi_step_loop(monkeypatch))
    _show(events, calls)

    served = [e["model"] for e in events if e.get("type") == "model"]
    assert served == [TOP, TOP, TOP]  # no failover needed
    assert [c["model"] for c in calls] == [TOP, TOP, TOP]
    tool_events = [e for e in events if e.get("type") == "tool_call"]
    text = " ".join(e.get("content", "") for e in events if e.get("type") in ("token", "text"))
    _assert_loop_completed(events, tool_events, text)


def _assert_loop_completed(events, tool_events, text):
    """Both runs must show a real multi-step loop ending in a final answer."""
    assert [e["tool"] for e in tool_events] == ["woo__list_products", "woo__list_orders"]
    assert all(e["outcome"] == "success" for e in tool_events)
    assert "found 2 products" in text
    # no error text at all: the turn never surfaced a failure category
    assert not any(e.get("type") == "text" and e.get("category") for e in events)
    # and the per-turn model cap was not what stopped the turn
    assert "model fallback cap" not in text
