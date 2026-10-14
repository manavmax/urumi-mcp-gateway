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

import chat.llm_fallback as fb
import pytest
from chat.llm_fallback import (
    CATEGORY_AUTH,
    CATEGORY_BAD_REQUEST,
    CATEGORY_BUSY,
    CATEGORY_MODEL_NOT_FOUND,
    CATEGORY_QUOTA,
    CATEGORY_UNKNOWN,
    DEFAULT_MAX_MODELS_PER_TURN,
    MODEL_COOLDOWNS,
    LLMBusyError,
    _create_with_fallback,
    _pick_category,
    _status_of,
    _strip_tool_signatures,
    error_category,
    is_transient,
)


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

    assert is_transient(TimeoutError()) is True
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
    _resp, served = asyncio.run(_create_with_fallback(
        create, ["gemini-a", "gemini-b"], {"messages": []},
        cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r1", remaining_budget=60,
    ))
    assert served == "gemini-b"
    assert _resp.choices[0].message.content == "from b"
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


# ---------------- MAX_MODELS_PER_TURN: per-turn cap on FAILED models (ADR-031) -----
# The bug this fixes: the cap used to count every model TRIED, so a model that SERVED a
# step spent the turn's budget. Four models (3 busy + 1 healthy) was enough to kill a
# still-working multi-step turn - the healthy model served step 1, and the loop died
# before step 2 with "model fallback cap: 4 models tried this turn".
# Now ONLY failures count, and the model that served step N is tried first for step N+1.


def test_max_models_per_turn_caps_the_failed_models():
    calls: list = []
    create = _fake_create({f"gemini-{c}": StatusError(503, "high demand") for c in "abcd"}, calls)
    with pytest.raises(LLMBusyError) as ei:
        asyncio.run(_create_with_fallback(
            create, ["gemini-a", "gemini-b", "gemini-c", "gemini-d"], {"messages": []},
            cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r7", remaining_budget=60,
            max_models=2,
        ))
    # the cap is on FAILURES, not on the configured chain length
    assert [c["model"] for c in calls] == ["gemini-a", "gemini-b"]
    assert ei.value.category == CATEGORY_BUSY
    assert "model fallback cap" in str(ei.value)
    assert "2 models failed this turn" in str(ei.value)


def test_the_model_that_served_does_not_spend_the_turn_budget():
    """The live bug: 3 busy models + 1 healthy model used to exhaust a 4-model cap,
    because the serve was counted as a model "tried"."""
    calls: list = []
    behaviors = {f"gemini-{c}": StatusError(503, "high demand") for c in "abc"}
    create = _fake_create(behaviors, calls)
    failed: list[str] = []
    _resp, served = asyncio.run(_create_with_fallback(
        create, ["gemini-a", "gemini-b", "gemini-c", "gemini-d"], {"messages": []},
        cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r7b", remaining_budget=60,
        max_models=4, failed_models=failed,  # 4 = the old cap value
    ))
    assert served == "gemini-d"
    assert failed == ["gemini-a", "gemini-b", "gemini-c"]  # ONLY failures are recorded

    # the same turn now asks for step 2. The old code had counted 4 models "tried" and
    # killed the turn here; now only 3 failures are charged and the sticky model serves.
    calls.clear()
    _resp2, served2 = asyncio.run(_create_with_fallback(
        create, ["gemini-d"], {"messages": []},
        cooldowns=MODEL_COOLDOWNS, producer_model="gemini-d", request_id="r7c", remaining_budget=60,
        max_models=4, failed_models=failed,
    ))
    assert served2 == "gemini-d"
    assert [c["model"] for c in calls] == ["gemini-d"]  # sticky: asked once, served

    # and once the failures DO reach the cap, the turn stops before asking anything new
    calls.clear()
    with pytest.raises(LLMBusyError) as ei:
        asyncio.run(_create_with_fallback(
            create, ["gemini-d", "gemini-e"], {"messages": []},
            cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r7e", remaining_budget=60,
            max_models=3, failed_models=["gemini-a", "gemini-b", "gemini-c"],
        ))
    assert calls == []  # nothing new was asked
    assert "model fallback cap" in str(ei.value)


def test_cap_charges_each_failure_once():
    """A failure is charged to the turn's budget exactly once, and the cap is checked
    BEFORE the next attempt - so N failures means at most N attempts."""
    calls: list = []
    failed: list[str] = []
    create = _fake_create(
        {"gemini-a": StatusError(503, "high demand"), "gemini-b": lambda kw: FakeResp("b")}, calls
    )
    with pytest.raises(LLMBusyError) as ei:
        asyncio.run(_create_with_fallback(
            create, ["gemini-a", "gemini-b"], {"messages": []},
            cooldowns=MODEL_COOLDOWNS, producer_model=None, request_id="r8", remaining_budget=60,
            max_models=1, failed_models=failed,
        ))
    assert [c["model"] for c in calls] == ["gemini-a"]  # stopped, gemini-b never called
    assert failed == ["gemini-a"]  # charged once
    assert ei.value.detail == "cap reached"


def test_sticky_chain_puts_the_serving_model_first():
    assert fb.sticky_chain(["a", "b", "c"], None) == ["a", "b", "c"]
    assert fb.sticky_chain(["a", "b", "c"], "c") == ["c", "a", "b"]
    assert fb.sticky_chain(["a", "b", "c"], "zzz") == ["a", "b", "c"]  # not in chain


def test_cooldown_skips_just_failed_model():
    MODEL_COOLDOWNS["gemini-a"] = time.monotonic() + 1000
    calls: list = []
    create = _fake_create({"gemini-b": lambda kw: FakeResp("b")}, calls)
    _resp, served = asyncio.run(_create_with_fallback(
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

    def max_models_per_turn(self):
        return DEFAULT_MAX_MODELS_PER_TURN


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


async def _run_chat(monkeypatch, behaviors, tools=None, max_models=None, chain=None):
    """Drive chat_loop end-to-end with a mock LLM; return (events, fake_completions).

    The test-only knobs live here, never in production code: `max_models` overrides the
    per-turn cap, `chain` the model order.
    """
    import chat.agent as agent
    import openai

    class Settings(_FakeSettings):
        def model_chain(self):
            return list(chain) if chain else ["gemini-a", "gemini-b"]

        def max_models_per_turn(self):
            return max_models if max_models is not None else DEFAULT_MAX_MODELS_PER_TURN

    monkeypatch.setattr(agent, "get_settings", lambda: Settings())

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


# ---- the live bug, end to end: 4-model chain, top 3 busy, 4th serves step 1 (ADR-031)


def _two_step_behaviors(failing, serving, *, fail_at_step: int = 0):
    """Serving model emits a tool call at step 1 and the final answer at step 2.

    `fail_at_step` > 0 makes the serving model itself fail from that step on (the next
    model of the chain then has to take over).
    """
    state = {"step": 0}

    def behavior(_kw):
        state["step"] += 1
        if fail_at_step and state["step"] >= fail_at_step:
            raise StatusError(503, "This model is currently experiencing high demand")
        if state["step"] == 1:
            return FakeResp(content="", tool_calls=[
                SimpleNamespace(id="call_1", function=SimpleNamespace(name="woo__list_products", arguments="{}"))
            ])
        return FakeResp("found 2 products")

    return {**failing, serving: behavior}


def test_top_models_busy_healthy_model_completes_both_steps(monkeypatch):
    """(5a) 3 models busy, the 4th serves step 1 AND step 2 -> the turn completes."""
    failing = {m: StatusError(503, "high demand") for m in ("gemini-a", "gemini-b", "gemini-c")}
    behaviors = _two_step_behaviors(failing, "gemini-d")
    chain = ["gemini-a", "gemini-b", "gemini-c", "gemini-d"]
    events, fake = asyncio.run(_run_chat(monkeypatch, behaviors, tools=[], chain=chain))

    served = [e["model"] for e in events if e.get("type") == "model"]
    text = _collect_text(events)
    # the healthy model carried the whole turn: it served step 1, and step 2 was asked
    # of it first again (sticky) instead of walking the chain from the top
    assert served == ["gemini-d", "gemini-d"]
    assert [c["model"] for c in fake.calls] == ["gemini-a", "gemini-b", "gemini-c", "gemini-d", "gemini-d"]
    assert "found 2 products" in text
    assert "model fallback cap" not in text
    assert not [e for e in events if e.get("type") == "text"]  # no error text at all


def test_serving_model_fails_at_step_two_next_model_takes_over(monkeypatch):
    """(5b) the model that served step 1 fails at step 2 -> the next model serves step 2."""
    state = {"step": 0}

    def d_behavior(_kw):
        state["step"] += 1
        if state["step"] == 1:
            return FakeResp(content="", tool_calls=[
                SimpleNamespace(id="call_1", function=SimpleNamespace(name="woo__list_products", arguments="{}"))
            ])
        raise StatusError(503, "This model is currently experiencing high demand")

    behaviors = {"gemini-a": StatusError(503, "high demand"),
                 "gemini-d": d_behavior,
                 "gemini-c": lambda kw: FakeResp("found 2 products")}
    chain = ["gemini-a", "gemini-d", "gemini-c"]
    events, fake = asyncio.run(_run_chat(monkeypatch, behaviors, tools=[], chain=chain))

    served = [e["model"] for e in events if e.get("type") == "model"]
    text = _collect_text(events)
    assert served == ["gemini-d", "gemini-c"]  # d served step 1, failed step 2, c took over
    assert "found 2 products" in text
    assert "model fallback cap" not in text
    # step 2 asked d first (sticky), then walked down the chain to c
    assert [c["model"] for c in fake.calls] == ["gemini-a", "gemini-d", "gemini-d", "gemini-c"]


def test_every_model_busy_gives_a_clear_message(monkeypatch):
    """(5c) all models busy -> the real category is named, and no cap/stack noise."""
    chain = ["gemini-a", "gemini-b", "gemini-c"]
    behaviors = {m: StatusError(503, "high demand") for m in chain}
    events, _ = asyncio.run(_run_chat(monkeypatch, behaviors, chain=chain))

    text = _collect_text(events)
    assert "AI models are busy, try again in a minute" in text
    assert "model fallback cap" not in text  # the cap was never reached: chain < cap
    assert "Traceback" not in text and "StatusError" not in text
    assert events[-1]["category"] == CATEGORY_BUSY


def test_long_busy_chain_still_names_the_real_category_and_the_cap(monkeypatch):
    """A chain longer than the cap stops at the cap, naming the category that caused it."""
    chain = [f"gemini-{c}" for c in "abcdefgh"]
    behaviors = {m: StatusError(503, "high demand") for m in chain}
    events, fake = asyncio.run(_run_chat(monkeypatch, behaviors, chain=chain, max_models=4))

    text = _collect_text(events)
    assert "AI models are busy" in text
    assert "model fallback cap: 4 models failed this turn" in text
    assert [c["model"] for c in fake.calls] == chain[:4]  # inspected, then stopped


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
    assert next(c for c in fake.calls if c["model"] == "gemini-a")
    assert "final answer" in _collect_text(events)
