"""LLM model fallback: try gateway.llm.models in priority order on transient errors.

Gemini's OpenAI-compatible endpoint frequently answers 503 "high demand" or 429.
Rather than failing the chat turn, move to the next model in the configured chain on
TRANSIENT errors only (429/500/502/503/504/timeout/connection). 400/401/403 are schema
or config bugs and MUST surface to the operator unchanged - never fall back on them.

Design (docs/DECISIONS.md ADR-029):
- models come ONLY from Helm values (gateway.llm.model + gateway.llm.models); no model
  name is hardcoded here.
- the OpenAI client is created with max_retries=0 so a failed attempt returns in
  seconds instead of after the client's internal 2-retry backoff.
- each attempt is bounded by the remaining overall turn budget (per-attempt timeout =
  min(30s, remaining)), so a multi-model fallback can never blow the 60s overall
  chat-turn budget (docs/05 §2 OVERALL_TIMEOUT).
- per-model cooldown: a model that just failed transiently is skipped for
  MODEL_COOLDOWN_SECONDS so every chat turn does not re-hit the dead model.
- logs are JSON, no secrets; the serving model is surfaced to the chat UI as a
  `model` event.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

logger = logging.getLogger("gateway.chat.llm_fallback")

MODEL_COOLDOWN_SECONDS = 45.0
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPT_SECONDS = 30.0

# module-level so cooldowns survive across chat turns (single-replica dev pod).
MODEL_COOLDOWNS: dict[str, float] = {}


class LLMBusyError(Exception):
    """Every model in the chain failed transiently; the turn should say so plainly."""


def _status_of(exc: BaseException) -> int | None:
    if isinstance(
        exc,
        (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
         httpx.RemoteProtocolError, httpx.NetworkError, asyncio.TimeoutError, ConnectionError, TimeoutError),
    ):
        return None  # transport-level: treated as transient below
    for attr in ("status_code", "status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def is_transient(exc: BaseException) -> bool:
    """True only when trying the next model can help (429/5xx/timeout/connection)."""
    if isinstance(
        exc,
        (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
         httpx.RemoteProtocolError, httpx.NetworkError, asyncio.TimeoutError, ConnectionError, TimeoutError),
    ):
        return True
    status = _status_of(exc)
    if status is None:
        # an openai.APIError with no HTTP status (e.g. transport failure) -> transient
        return True
    return status in TRANSIENT_STATUSES


def _strip_tool_signatures(messages: list[dict]) -> list[dict]:
    """Remove `extra_content` (Gemini thought_signature) from echoed tool_calls.

    thought_signature is model-specific: a signature produced by model A is rejected by
    model B's endpoint (400). We keep them when the SAME model continues the turn and
    strip them on failover to a different model. The canonical `messages` list is left
    untouched (a copy is returned) so a later same-model call still has its signature.
    """
    out = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            tcs = []
            for tc in m["tool_calls"]:
                t = dict(tc)
                t.pop("extra_content", None)
                tcs.append(t)
            m = {**m, "tool_calls": tcs}
        out.append(m)
    return out


async def _create_with_fallback(
    create,
    model_chain: list[str],
    kwargs: dict,
    *,
    cooldowns: dict[str, float],
    producer_model: str | None,
    request_id: str,
    remaining_budget: float,
) -> tuple[object, str]:
    """Try models in priority order; move to the next on transient errors.

    Returns (response, serving_model). Raises LLMBusyError when every model failed
    transiently (or was in cooldown). Raises the original exception for non-transient
    errors (400/401/403) - no fallback, surface the bug clearly.
    """
    skipped: list[dict] = []
    last_transient: BaseException | None = None
    for model in model_chain:
        now = time.monotonic()
        cool_until = cooldowns.get(model, 0.0)
        if now < cool_until:
            info = {"reason": "cooldown", "seconds_left": round(cool_until - now, 1)}
            skipped.append({"model": model, **info})
            logger.info(json.dumps({"event": "llm_model_skipped", "model": model, "request_id": request_id, **info}))
            continue

        stripped = producer_model is not None and model != producer_model
        send_messages = _strip_tool_signatures(kwargs["messages"]) if stripped else kwargs["messages"]
        attempt_kwargs = {**kwargs, "messages": send_messages}
        attempt_timeout = min(MAX_ATTEMPT_SECONDS, remaining_budget)
        if attempt_timeout <= 1:
            raise LLMBusyError("AI models are busy, try again in a minute")
        try:
            resp = await asyncio.wait_for(create(model=model, **attempt_kwargs), timeout=attempt_timeout)
            cooldowns.pop(model, None)
            logger.info(json.dumps({
                "event": "llm_model_served",
                "model": model,
                "request_id": request_id,
                "stripped_signatures": stripped,
                "skipped": skipped,
            }))
            return resp, model
        except BaseException as exc:  # noqa: BLE001 - deliberate; see is_transient
            if not is_transient(exc):
                raise  # 400/401/403 etc: config/schema bug, never fall back
            cooldowns[model] = time.monotonic() + MODEL_COOLDOWN_SECONDS
            last_transient = exc
            skipped.append({"model": model, "reason": "failed", "error_type": type(exc).__name__,
                            "status": _status_of(exc), "detail": str(exc)[:200]})
            logger.warning(json.dumps({
                "event": "llm_model_failed",
                "model": model,
                "request_id": request_id,
                "status": _status_of(exc),
                "error_type": type(exc).__name__,
                "detail": str(exc)[:200],
            }))

    raise LLMBusyError("AI models are busy, try again in a minute") from last_transient
