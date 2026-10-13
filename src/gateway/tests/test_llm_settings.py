"""LLM settings: model chain and the per-turn model-failure cap (ADR-029/ADR-031).

The cap must come from Helm (gateway.llm.maxModelsPerTurn -> OPENAI_MAX_MODELS_PER_TURN),
not from a constant, and a nonsense value must never disable it.
"""

from __future__ import annotations

import chat.llm_fallback as fb
from config import Settings


def _settings(**extra) -> Settings:
    base = {
        "openai_api_key": "test-key-not-real",
        "openai_base_url": "https://example.invalid/v1",
        "openai_model": "gemini-a",
        "openai_models": "",
    }
    base.update(extra)
    return Settings(**base)


def test_max_models_per_turn_defaults_to_six():
    assert fb.DEFAULT_MAX_MODELS_PER_TURN == 6
    assert _settings().max_models_per_turn() == 6


def test_max_models_per_turn_reads_the_helm_value():
    assert _settings(openai_max_models_per_turn=3).max_models_per_turn() == 3
    assert _settings(openai_max_models_per_turn=12).max_models_per_turn() == 12


def test_max_models_per_turn_clamps_nonsense_values():
    # 0 / negative / unparsable must not disable the cap - one turn could otherwise
    # burn the whole configured chain on every iteration. pydantic rejects an unparsable
    # env var at startup, so bypass validation to prove the clamp still holds.
    assert _settings(openai_max_models_per_turn=0).max_models_per_turn() == 6
    assert _settings(openai_max_models_per_turn=-1).max_models_per_turn() == 6
    s = _settings()
    s.openai_max_models_per_turn = "not-a-number"  # type: ignore[assignment]
    assert s.max_models_per_turn() == 6


def test_model_chain_is_still_derived_from_helm_values_only():
    s = _settings(openai_models="gemini-b, gemini-c,gemini-b")
    assert s.model_chain() == ["gemini-a", "gemini-b", "gemini-c"]
