"""Chat agent tool-call echo (docs/09, Gemini OpenAI-compat).

Gemini's OpenAI-compatible endpoint rejects a follow-up request whose assistant message
echoes tool_calls without the `extra_content` (google.thought_signature) field. The
gateway must preserve `extra_content` verbatim when building the assistant message that
carries tool_calls back, otherwise multi-step tool loops break with a 400. This also
must be a no-op for OpenAI (no extra_content on the response).
"""

from __future__ import annotations

from types import SimpleNamespace

from chat.agent import _assistant_message_with_tool_calls


def _make_tool_call(*, id_="call_1", name="woo__list_products", args="{}", extra=None):
    return SimpleNamespace(
        id=id_,
        function=SimpleNamespace(name=name, arguments=args),
        extra_content=extra,
    )


def test_echo_preserves_gemini_thought_signature():
    tc = _make_tool_call(extra={"google": {"thought_signature": "sig-123"}})
    msg = _assistant_message_with_tool_calls("", [tc])
    echo = msg["tool_calls"][0]
    assert echo["id"] == "call_1"
    assert echo["function"]["name"] == "woo__list_products"
    assert echo["function"]["arguments"] == "{}"
    assert echo["extra_content"] == {"google": {"thought_signature": "sig-123"}}


def test_echo_is_noop_when_no_extra_content():
    # Plain OpenAI endpoints never attach extra_content: the echo must still be well-formed
    # and simply carry extra_content: None (the SDK drops it when serializing).
    tc = _make_tool_call()
    msg = _assistant_message_with_tool_calls("thinking", [tc])
    assert msg["content"] == "thinking"
    echo = msg["tool_calls"][0]
    assert echo["extra_content"] is None
    assert echo["function"]["name"] == "woo__list_products"


def test_echo_keeps_role_and_shape():
    tc = _make_tool_call(id_="call_9", name="woo__get_order", args='{"id": 1}')
    msg = _assistant_message_with_tool_calls("using tools", [tc])
    assert msg["role"] == "assistant"
    assert len(msg["tool_calls"]) == 1
    call = msg["tool_calls"][0]
    assert call["type"] == "function"
    assert call["id"] == "call_9"
    assert call["function"]["name"] == "woo__get_order"
    assert call["function"]["arguments"] == '{"id": 1}'
    # provider-neutral: an OpenAI-only endpoint never sees extra_content
    assert "extra_content" in call
