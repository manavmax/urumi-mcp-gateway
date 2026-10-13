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
    # and must NOT carry an extra_content key. Gemini attaches thought_signature only to
    # the first function-call part of a turn and leaves the rest null; a literal
    # "extra_content": null is rejected with 400 "Value is not a struct: null", so the
    # key is omitted entirely when the model returned no signature.
    tc = _make_tool_call()
    msg = _assistant_message_with_tool_calls("thinking", [tc])
    assert msg["content"] == "thinking"
    echo = msg["tool_calls"][0]
    assert "extra_content" not in echo
    assert echo["function"]["name"] == "woo__list_products"


def test_echo_omits_null_signature_but_keeps_real_one():
    # The exact live multi-step failure: a turn with two tool calls where only the first
    # carries a google.thought_signature. Echoing the null second one produces
    # 400 "Value is not a struct: null"; omitting it keeps the request valid.
    tcs = [
        _make_tool_call(id_="call_1", extra={"google": {"thought_signature": "sig-abc"}}),
        _make_tool_call(id_="call_2", name="woo__list_orders", extra=None),
    ]
    msg = _assistant_message_with_tool_calls("", tcs)
    first, second = msg["tool_calls"]
    assert first["extra_content"] == {"google": {"thought_signature": "sig-abc"}}
    assert "extra_content" not in second
    assert second["function"]["name"] == "woo__list_orders"


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
    # provider-neutral: an OpenAI-only endpoint never sees extra_content, and the key is
    # absent rather than echoed as null (Gemini rejects null with a 400)
    assert "extra_content" not in call
