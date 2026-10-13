"""LLM model fallback (docs/DECISIONS.md ADR-029, extended by ADR-030).

Gemini's OpenAI-compatible endpoint frequently answers 503 "high demand" / 429. The
gateway must fail over to the next model in the configured chain on TRANSIENT errors
only, keep a per-model cooldown, never fall back on 400/401/403, name the REAL failure
category (quota / busy / auth / model-not-found / ...) instead of always saying "busy",
and cap how many models a single turn may try. Tested against a MOCK LLM so every
branch is deterministic.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

import chat.llm_fallback as fb
from chat.llm_fallback import (
    CATEGORY_AUTH,
    CATEGORY_BAD_REQUEST,
    CATEGORY_BUSY,
    CATEGORY_MODEL_NOT_FOUND,
    CATEGORY_QUOTA,
    CATEGORY_UNKNOWN,
    LLMBusyError,
    MAX_MODELS_PER_TURN,
    MODEL_COOLDOWNS,
    _create_with_fallback,
    _pick_category,
    _status_of,
    _strip_tool_signatures,
    error_category,
    is_transient,
)


@pytest.fixture(autouse=True)
def _reset_cooldowns():
    MODEL_COOLDOWNS.clear()
    yield
    MODEL_COOLDOWNS.clear()


class StatusError(Exception):
    """Minimal stand-in for openai.APIStatusError carrying an HTTP status."""

    def __init__(self, status: int, message: str = ""):
        super().__init__(message or f"http {status}")
        self.status_code = status


class FakeResp:
    def __init__(self, content: str = "ok", tool_calls=None):
        msg = SimpleNamespace(content=content, tool_calls=tool_calls or [])
        self.choices = [SimpleNamespace(message=msg)]


# ---------------- is_transient ----------------


def test_transient_statuses_are_transient():
    for code in (429, 500, 502, 503, 504):
        assert is_transient(StatusError(code)) is True, code


def test_config_bugs_are_not_transient():
    for code in (400, 401, 403):
        assert is_transient(StatusError(code)) is False, code


def test_timeouts_and_connection_errors_are_transient():
    import httpx

    assert is_transient(asyncio.TimeoutError()) is True
    assert is_transient(httpx.ConnectError("boom")) is True
    assert is_transient(httpx.ReadTimeout("boom")) is True


def test_status_of_extracts_http_status():
    assert _status_of(StatusError(503)) == 503


# ---------------- error_category (ADR-030: the real category, not always "busy") ----


def test_quota_is_named_when_the_provider_says_quota():
    # a 429 that spells out a spent quota is terminal: retrying cannot help, so it must
    # NOT be reported as "busy, try again in a minute".
    exc = StatusError(429, "Quota exceeded for quota metric 'generate requests free tier'")
    assert error_category(exc) == CATEGORY_QUOTA


def test_plain_429_and_5xx_are_busy_not_quota():
    assert error_category(StatusError(429, "Too many requests / rate limit")) == CATEGORY_BUSY
    assert error_category(StatusError(503, "This model is currently experiencing high demand")) == CATEGORY_BUSY
    assert error_category(StatusError(504, "deadline exceeded")) == CATEGORY_BUSY


def test_auth_failures_are_named_auth():
    assert error_category(StatusError(401, "API key not valid")) == CATEGORY_AUTH
    assert error_category(StatusError(403, "permission denied")) == CATEGORY_AUTH


def test_missing_model_is_named_model_not_found():
    assert error_category(StatusError(404, "models/gemini-x is not found for API version v1beta")) == CATEGORY_MODEL_NOT_FOUND


def test_400_is_named_bad_request():
    assert error_category(StatusError(400, "Function call is missing a thought_signature")) == CATEGORY_BAD_REQUEST


def test_transport_failure_without_status_is_unknown():
    import httpx

    assert error_category(httpx.ReadTimeout("no response in 30s")) == CATEGORY_UNKNOWN


def test_pick_category_prefers_the_actionable_cause():
    assert _pick_category({CATEGORY_BUSY, CATEGORY_QUOTA}) == CATEGORY_QUOTA
    assert _pick_category({CATEGORY_BUSY, CATEGORY_AUTH}) == CATEGORY_AUTH
    assert _pick_category({CATEGORY_UNKNOWN, CATEGORY_BUSY}) == CATEGORY_BUSY
    assert _pick_category(set()) == CATEGORY_UNKNOWN


# ---------------- signature stripping (Gemini thought_signature on failover) ----------------


def _asst_msg_with_sig():
    tc = {"id": "call_1", "type": "function",
          "function": {"name": "woo__list_products", "arguments": "{}"},
          "extra_content": {"google": {"thought_signature": "sig-A"}}}
    return {"role": "assistant", "content": "", "tool_calls": [tc]}


def test_strip_tool_signatures_removes_extra_content_only():
    msgs = [_asst_msg_with_sig(), {"role": "user", "content": "hi"}]
    out = _strip_tool_signatures(msgs)
    assert "extra_content" not in out[0]["tool_calls"][0]
    assert out[1] == msgs[1]
    assert "extra_content" in msgs[0]["tool_calls"][0]  # canonical untouched


def test_strip_signatures_is_noop_without_tool_calls():
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "plain"}]
    assert _strip_tool_signatures(msgs) == msgs


# ---------------- _create_with_fallback ----------------


def _fake_create(behaviors: dict, calls: list):
    async def create(**kwargs):
        model = kwargs["model"]
        calls.append({"model": model, "messages": kwargs.get("messages")})
        b = behaviors.get(model)
        if isinstance(b, BaseException):
            raise b
        return b(kwargs) if callable(b) else FakeResp()

    return create


def test_first_model_503_second_succeeds():
    calls: list = []
    create = _fake_create(
        {"gemini-a": StatusError(503, "high demand"), "gemini-b": lambda kw: FakeResp("from b")},
        calls,
    )
    resp, served = asyncio.run(_create_with_fallback(
        create, ["gemini-a", "gemini-b"], {"messages": []},
        cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r1", remaining_budget=60,
    ))
    assert served == "gemini-b"
    assert resp.choices[0].message.content == "from b"
    assert [c["model"] for c in calls] == ["gemini-a", "gemini-b"]
    assert MODEL_COOLDOWNS["gemini-a"] > 0


def test_400_does_not_fall_back():
    calls: list = []
    create = _fake_create({"gemini-a": StatusError(400, "schema bug")}, calls)
    with pytest.raises(StatusError) as ei:
        asyncio.run(_create_with_fallback(
            create, ["gemini-a", "gemini-b"], {"messages": []},
            cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r2", remaining_budget=60,
        ))
    assert ei.value.status_code == 400
    assert [c["model"] for c in calls] == ["gemini-a"]  # no fallback on config/schema bug


def test_all_fail_raises_busy():
    create = _fake_create(
        {"gemini-a": StatusError(503, "high demand"), "gemini-b": StatusError(429, "rate limit")}, []
    )
    with pytest.raises(LLMBusyError):
        asyncio.run(_create_with_fallback(
            create, ["gemini-a", "gemini-b"], {"messages": []},
            cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r3", remaining_budget=60,
        ))


def test_all_fail_busy_keeps_the_busy_message():
    create = _fake_create(
        {"gemini-a": StatusError(503, "high demand"), "gemini-b": StatusError(429, "too many requests")}, []
    )
    with pytest.raises(LLMBusyError) as ei:
        asyncio.run(_create_with_fallback(
            create, ["gemini-a", "gemini-b"], {"messages": []},
            cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r3b", remaining_budget=60,
        ))
    assert ei.value.category == CATEGORY_BUSY
    assert str(ei.value) == "AI models are busy, try again in a minute"


def test_all_fail_quota_names_the_real_category():
    create = _fake_create(
        {"gemini-a": StatusError(429, "Quota exceeded for quota metric 'generate requests'"),
         "gemini-b": StatusError(503, "high demand")},
        [],
    )
    with pytest.raises(LLMBusyError) as ei:
        asyncio.run(_create_with_fallback(
            create, ["gemini-a", "gemini-b"], {"messages": []},
            cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r3c", remaining_budget=60,
        ))
    assert ei.value.category == CATEGORY_QUOTA
    assert "quota" in str(ei.value).lower()
    assert str(ei.value) != "AI models are busy, try again in a minute"


def test_all_in_cooldown_raises_busy_without_calling_any_model():
    calls: list = []
    create = _fake_create({"gemini-a": lambda kw: FakeResp("a")}, calls)
    MODEL_COOLDOWNS["gemini-a"] = time.monotonic() + 1000
    with pytest.raises(LLMBusyError) as ei:
        asyncio.run(_create_with_fallback(
            create, ["gemini-a"], {"messages": []},
            cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r3d", remaining_budget=60,
        ))
    assert ei.value.category == CATEGORY_BUSY
    assert calls == []


# ---------------- MAX_MODELS_PER_TURN (per-turn model cap, not a tool-call cap) ----


def test_max_models_per_turn_caps_the_chain():
    calls: list = []
    create = _fake_create({f"gemini-{c}": StatusError(503, "high demand") for c in "abcd"}, calls)
    with pytest.raises(LLMBusyError) as ei:
        asyncio.run(_create_with_fallback(
            create, ["gemini-a", "gemini-b", "gemini-c", "gemini-d"], {"messages": []},
            cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r7", remaining_budget=60,
            max_models=2,
        ))
    # the cap is on TRIES, not on the configured chain length
    assert [c["model"] for c in calls] == ["gemini-a", "gemini-b"]
    assert ei.value.category == CATEGORY_BUSY
    assert "model fallback cap" in str(ei.value)
    assert "2" in str(ei.value)


def test_cap_counts_the_models_already_tried_this_turn():
    """The counter is the caller's: a turn that already burned its budget must not get
    a fresh allowance on the next tool-loop iteration."""
    calls: list = []
    tried = ["gemini-a", "gemini-b"]
    create = _fake_create({"gemini-c": lambda kw: FakeResp("c")}, calls)
    with pytest.raises(LLMBusyError) as ei:
        asyncio.run(_create_with_fallback(
            create, ["gemini-c", "gemini-d"], {"messages": []},
            cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r8", remaining_budget=60,
            max_models=2, models_tried=tried,
        ))
    assert calls == []  # nothing new was tried
    assert ei.value.detail == "cap reached"


def test_cap_is_independent_of_the_tool_call_cap():
    from chat import agent

    assert agent.MAX_MODELS_PER_TURN == MAX_MODELS_PER_TURN
    assert agent.MAX_MODELS_PER_TURN != agent.MAX_TOOL_CALLS  # separate budgets (docs/05 §2)


def test_cooldown_skips_just_failed_model():
    MODEL_COOLDOWNS["gemini-a"] = time.monotonic() + 1000
    calls: list = []
    create = _fake_create({"gemini-b": lambda kw: FakeResp("b")}, calls)
    resp, served = asyncio.run(_create_with_fallback(
        create, ["gemini-a", "gemini-b"], {"messages": []},
        cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r4", remaining_budget=60,
    ))
    assert served == "gemini-b"
    assert [c["model"] for c in calls] == ["gemini-b"]  # gemini-a skipped, never called


def test_signatures_stripped_when_producer_model_differs():
    calls: list = []
    msgs = [_asst_msg_with_sig()]
    create = _fake_create({"gemini-b": lambda kw: FakeResp("b")}, calls)
    asyncio.run(_create_with_fallback(
        create, ["gemini-b"], {"messages": msgs},
        cooldowns=MODEL_COOLDOWNS, producer_model="gemini-a", request_id="r5", remaining_budget=60,
    ))
    assert "extra_content" not in calls[0]["messages"][0]["tool_calls"][0]


def test_signatures_kept_when_same_model_continues():
    calls: list = []
    msgs = [_asst_msg_with_sig()]
    create = _fake_create({"gemini-a": lambda kw: FakeResp("a")}, calls)
    asyncio.run(_create_with_fallback(
        create, ["gemini-a"], {"messages": msgs},
        cooldowns=MODEL_COOLDOWNS, producer_model="gemini-a", request_id="r6", remaining_budget=60,
    ))
    assert calls[0]["messages"][0]["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "sig-A"}}


# ---------------- chat_loop integration with a mock LLM ----------------


class _FakeSettings:
    openai_api_key = "test-key-not-real"
    openai_base_url = None
    openai_model = "gemini-a"
    openai_models = "gemini-a,gemini-b"

    def model_chain(self):
        return ["gemini-a", "gemini-b"]


class _FakeCompletions:
    def __init__(self, behaviors):
        self._behaviors = behaviors
        self.calls = []

    async def create(self, **kwargs):
        model = kwargs["model"]
        self.calls.append({"model": model, "messages": kwargs.get("messages")})
        b = self._behaviors.get(model)
        if isinstance(b, BaseException):
            raise b
        return b(kwargs) if callable(b) else FakeResp()


async def _run_chat(monkeypatch, behaviors, tools=None, max_models=None):
    """Drive chat_loop end-to-end with a mock LLM; return (events, fake_completions).

    `max_models` overrides the per-turn model cap (the test-only knobs for the switch
    and the cap live here, never in production code).
    """
    import openai

    import chat.agent as agent

    monkeypatch.setattr(agent, "get_settings", lambda: _FakeSettings())
    if max_models is not None:
        monkeypatch.setattr(agent, "MAX_MODELS_PER_TURN", max_models)

    async def _fake_allowed(_db):
        return tools or []

    monkeypatch.setattr(agent, "_get_allowed_tools", _fake_allowed)

    fake_cc = _FakeCompletions(behaviors)

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=fake_cc.create))

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeOpenAI)

    db = object()
    user = SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
    events = []
    async for evt in agent.chat_loop(db, user, [{"role": "user", "content": "hi"}], "req-test-1"):
        events.append(evt)
    return events, fake_cc


def _collect_text(events) -> str:
    return " ".join(e.get("content", "") for e in events if e.get("type") in ("token", "text"))


def test_chat_fails_over_to_second_model_and_reports_it(monkeypatch):
    behaviors = {
        "gemini-a": StatusError(503, "high demand"),
        "gemini-b": lambda kw: FakeResp("answered by b"),
    }
    events, fake = asyncio.run(_run_chat(monkeypatch, behaviors))
    assert [e.get("model") for e in events if e.get("type") == "model"] == ["gemini-b"]
    assert "answered by b" in _collect_text(events)
    assert [c["model"] for c in fake.calls] == ["gemini-a", "gemini-b"]


def test_chat_all_models_busy_returns_clear_message(monkeypatch):
    behaviors = {"gemini-a": StatusError(503, "high demand"), "gemini-b": StatusError(429, "rate limit")}
    events, _ = asyncio.run(_run_chat(monkeypatch, behaviors))
    text = _collect_text(events)
    assert "AI models are busy, try again in a minute" in text
    assert "stack" not in text and "Traceback" not in text
    assert events[-1]["type"] == "text" and events[-1]["category"] == CATEGORY_BUSY


def test_chat_quota_exhaustion_names_the_real_category(monkeypatch):
    """A spent quota is NOT "busy": the message must say quota so the operator knows
    retrying will not help (ADR-030)."""
    behaviors = {
        "gemini-a": StatusError(429, "Quota exceeded for quota metric 'generate requests free tier'"),
        "gemini-b": StatusError(503, "high demand"),
    }
    events, _ = asyncio.run(_run_chat(monkeypatch, behaviors))
    text = _collect_text(events)
    assert "quota" in text.lower()
    assert "busy" not in text.lower()
    assert events[-1]["category"] == CATEGORY_QUOTA


def test_chat_auth_failure_names_auth_category(monkeypatch):
    behaviors = {"gemini-a": StatusError(401, "API key not valid. Please pass a valid key.")}
    events, fake = asyncio.run(_run_chat(monkeypatch, behaviors))
    text = _collect_text(events)
    assert "auth" in text
    assert "LLM error" in text
    assert [c["model"] for c in fake.calls] == ["gemini-a"]  # no fallback on a config bug


def test_chat_model_not_found_names_the_category(monkeypatch):
    behaviors = {"gemini-a": StatusError(404, "models/gemini-x is not found for API version v1beta")}
    events, fake = asyncio.run(_run_chat(monkeypatch, behaviors))
    text = _collect_text(events)
    assert "model-not-found" in text
    assert [c["model"] for c in fake.calls] == ["gemini-a"]


def test_chat_model_cap_is_shared_across_the_tool_loop(monkeypatch):
    """The cap counts models for the WHOLE turn: once it is reached the turn stops with
    an operator-visible message instead of trying a fresh model on the next iteration."""
    steps = {"n": 0}

    def tool_call():
        return SimpleNamespace(id="call_1", function=SimpleNamespace(name="woo__list_products", arguments="{}"))

    def b_behavior(_kw):
        steps["n"] += 1
        if steps["n"] == 1:
            return FakeResp(content="", tool_calls=[tool_call()])
        return FakeResp("final answer")

    behaviors = {"gemini-a": StatusError(503, "high demand"), "gemini-b": b_behavior}
    events, fake = asyncio.run(_run_chat(monkeypatch, behaviors, tools=[], max_models=2))

    # a failed once (then cooled down), b served the tool step - that is 2 models, the cap
    assert [c["model"] for c in fake.calls] == ["gemini-a", "gemini-b"]
    assert len([e for e in events if e.get("type") == "tool_call"]) == 1
    text = _collect_text(events)
    assert "model fallback cap" in text
    assert "busy" in text.lower()
    assert "final answer" not in text  # the turn ended at the cap, it did not keep looping


def test_chat_400_surfaces_without_fallback(monkeypatch):
    behaviors = {"gemini-a": StatusError(400, "function call is missing a thought_signature")}
    events, fake = asyncio.run(_run_chat(monkeypatch, behaviors))
    text = _collect_text(events)
    assert "LLM error" in text
    assert "thought_signature" in text
    assert [c["model"] for c in fake.calls] == ["gemini-a"]  # no fallback on 400


def test_chat_failover_strips_thought_signature_between_models(monkeypatch):
    """Step 1: model A serves and emits a tool_call with its thought_signature. Step 2:
    A is transiently down, B serves — B must NOT receive A's signature (model-specific)."""
    a_calls = {"n": 0}

    def tc_with_sig():
        return SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(name="woo__list_products", arguments="{}"),
            extra_content={"google": {"thought_signature": "sig-A"}},
        )

    def a_behavior(_kw):
        a_calls["n"] += 1
        if a_calls["n"] == 1:
            return FakeResp(content="", tool_calls=[tc_with_sig()])  # step 1
        raise StatusError(503, "high demand")  # step 2: down again -> failover to B

    behaviors = {"gemini-a": a_behavior, "gemini-b": lambda kw: FakeResp("final answer")}
    events, fake = asyncio.run(_run_chat(monkeypatch, behaviors, tools=[]))

    served = [e["model"] for e in events if e.get("type") == "model"]
    assert served == ["gemini-a", "gemini-b"]

    # B must not receive A's thought_signature anywhere in the echoed history
    b_call = next(c for c in fake.calls if c["model"] == "gemini-b")
    for m in b_call["messages"]:
        for tc in m.get("tool_calls", []):
            assert "extra_content" not in tc
    # A's step-1 echo (same-model continue within its own turn) kept the signature
    a_call = next(c for c in fake.calls if c["model"] == "gemini-a")
    assert "final answer" in _collect_text(events)
