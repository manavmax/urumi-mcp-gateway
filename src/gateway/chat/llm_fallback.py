"""LLM model fallback: try gateway.llm.models in priority order on transient errors.

Gemini's OpenAI-compatible endpoint frequently answers 503 "high demand" or 429.
Rather than failing the chat turn, move to the next model in the configured chain on
TRANSIENT errors only (429/500/502/503/504/timeout/connection). 400/401/403 are schema
or config bugs and MUST surface to the operator unchanged - never fall back on them.

Design (docs/DECISIONS.md ADR-029, extended by ADR-030):
- models come ONLY from Helm values (gateway.llm.model + gateway.llm.models); no model
  name is hardcoded here.
- the OpenAI client is created with max_retries=0 so a failed attempt returns in
  seconds instead of after the client's internal 2-retry backoff.
- each attempt is bounded by the remaining overall turn budget (per-attempt timeout =
  min(30s, remaining)), so a multi-model fallback can never blow the 60s overall
  chat-turn budget (docs/05 §2 OVERALL_TIMEOUT).
- per-model cooldown: a model that just failed transiently is skipped for
  MODEL_COOLDOWN_SECONDS so every chat turn does not re-hit the dead model.
- MAX_MODELS_PER_TURN (Helm `gateway.llm.maxModelsPerTurn`, default 6) caps how many
  models may FAIL in one chat turn, counted ACROSS the tool-loop iterations of that
  turn. ONLY failures count - the model that served a step never consumes the budget,
  because a turn that is working must not be killed by its own success. It is a
  separate budget from the agent's MAX_TOOL_CALLS: that one bounds how much a model may
  DO to the store, this one bounds how much of the configured chain a single turn may
  burn.
- STICKY serving model: the model that produced the last step is tried FIRST for the
  next step of the same turn, so a healthy model is not abandoned just because the
  chain's first entry was busy. If the sticky model fails, the chain is walked in
  normal priority order from the top.
- the chat error message names the real failure category (quota / busy / auth /
  model-not-found / bad-request / unknown) instead of always saying "busy", and it says
  so when a write tool already succeeded in that turn (nothing was rolled back).
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

# Default per-turn cap on FAILED models; the live value is the Helm value
# gateway.llm.maxModelsPerTurn -> OPENAI_MAX_MODELS_PER_TURN (config.py).
DEFAULT_MAX_MODELS_PER_TURN = 6

# module-level so cooldowns survive across chat turns (single-replica dev pod).
MODEL_COOLDOWNS: dict[str, float] = {}

# ---- failure categories (ADR-030) ------------------------------------------------
# The chat turn must say WHY the models failed, because the operator's next action is
# different for each: "busy" = retry in a minute, "quota" = the key's quota is spent,
# "auth" = the Secret key is wrong, "model-not-found" = a Helm value names a model the
# provider does not serve.
CATEGORY_QUOTA = "quota"
CATEGORY_BUSY = "busy"
CATEGORY_AUTH = "auth"
CATEGORY_MODEL_NOT_FOUND = "model-not-found"
CATEGORY_BAD_REQUEST = "bad-request"
CATEGORY_UNKNOWN = "unknown"

CATEGORY_MESSAGES: dict[str, str] = {
    CATEGORY_QUOTA: "AI models are over quota: the LLM key's quota is exhausted. Retry after the quota resets, or use a paid-tier key.",
    CATEGORY_BUSY: "AI models are busy, try again in a minute",
    CATEGORY_AUTH: "AI model authentication failed (401/403): the LLM provider rejected the key in the gateway-llm Secret.",
    CATEGORY_MODEL_NOT_FOUND: "AI model not found (404): gateway.llm.model / gateway.llm.models names a model the provider does not serve.",
    CATEGORY_BAD_REQUEST: "AI model rejected the request (400): a tool schema or message is malformed.",
    CATEGORY_UNKNOWN: "AI models are unavailable, try again in a minute",
}

# Most actionable first: a wrong model name or a bad key is an operator fix, a spent
# quota is terminal for now, and busy/unknown are "wait and retry".
_CATEGORY_PRIORITY = (
    CATEGORY_MODEL_NOT_FOUND,
    CATEGORY_AUTH,
    CATEGORY_BAD_REQUEST,
    CATEGORY_QUOTA,
    CATEGORY_BUSY,
    CATEGORY_UNKNOWN,
)

QUOTA_MARKERS = ("quota", "resource_exhausted", "resource exhausted", "plan and billing")
NOT_FOUND_MARKERS = ("is not found for api version", "model not found", "unknown model", "does not exist")


class LLMBusyError(Exception):
    """Every model in the chain failed, or the per-turn model cap was reached.

    Carries the real failure `category` (quota / busy / auth / model-not-found /
    bad-request / unknown) and a short `detail`, so the chat turn can name the cause
    instead of always claiming the models are busy.
    """

    def __init__(self, message: str = "", *, category: str = CATEGORY_BUSY, detail: str = ""):
        self.message = message or CATEGORY_MESSAGES.get(category, CATEGORY_MESSAGES[CATEGORY_UNKNOWN])
        super().__init__(self.message)
        self.category = category
        self.detail = detail


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


def error_category(exc: BaseException) -> str:
    """Classify an LLM failure into one real category (ADR-030).

    The HTTP status decides first, the response text only refines it: a 429/5xx is
    "busy" unless the provider spells out a spent quota (then "quota" - retrying will
    NOT help), 401/403 are "auth", 404 (or any text naming the model as absent) is
    "model-not-found", 400/422 are "bad-request". A transport failure with no status at
    all is "unknown": we cannot honestly claim more than that the models did not answer.
    """
    status = _status_of(exc)
    text = str(exc).lower()
    if status is None:
        return CATEGORY_UNKNOWN
    if any(m in text for m in NOT_FOUND_MARKERS):
        return CATEGORY_MODEL_NOT_FOUND
    if status in (401, 403):
        return CATEGORY_QUOTA if any(m in text for m in QUOTA_MARKERS) else CATEGORY_AUTH
    if status == 404:
        return CATEGORY_MODEL_NOT_FOUND
    if status in TRANSIENT_STATUSES:
        return CATEGORY_QUOTA if any(m in text for m in QUOTA_MARKERS) else CATEGORY_BUSY
    if status in (400, 422):
        return CATEGORY_BAD_REQUEST
    return CATEGORY_UNKNOWN


def _pick_category(categories) -> str:
    """Single category to report when several models failed differently."""
    cats = set(categories)
    for c in _CATEGORY_PRIORITY:
        if c in cats:
            return c
    return CATEGORY_UNKNOWN


def category_message(category: str, note: str = "") -> str:
    """User-facing message for a category, with an optional operator-visible note."""
    msg = CATEGORY_MESSAGES.get(category, CATEGORY_MESSAGES[CATEGORY_UNKNOWN])
    return f"{msg} ({note})" if note else msg


def sticky_chain(model_chain: list[str], producer_model: str | None) -> list[str]:
    """Order the chain for the next step: the model that just SERVED goes first.

    Without this, a working model is abandoned as soon as one earlier entry of the
    chain recovers from its cooldown, and the turn pays a fresh 503 for every step.
    With it, a healthy model keeps the turn; only when the sticky model itself fails
    does the chain get walked in normal priority order.
    """
    if not producer_model or producer_model not in model_chain:
        return list(model_chain)
    return [producer_model] + [m for m in model_chain if m != producer_model]


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
    max_models: int = DEFAULT_MAX_MODELS_PER_TURN,
    failed_models: list[str] | None = None,
) -> tuple[object, str]:
    """Try models in priority order; move to the next on transient errors.

    Returns (response, serving_model). Raises LLMBusyError when every model failed
    transiently (or was in cooldown, or the per-turn failure cap was reached), carrying
    the real failure category. Raises the original exception for non-transient errors
    (400/401/403) - no fallback, surface the bug clearly.

    `failed_models` is the caller's per-turn counter (the agent passes one list for the
    whole chat turn). ONLY a model that FAILED is appended to it, so the cap bounds the
    failures a turn may burn - never the models that served it. A turn where the top 3
    models are busy and the 4th serves both steps of a tool loop completes normally.

    The chain is walked STICKY: `producer_model` (the model that served the previous
    step) is tried first.
    """
    failed = failed_models if failed_models is not None else []
    skipped: list[dict] = []
    categories: set[str] = set()
    last_transient: BaseException | None = None
    for model in sticky_chain(model_chain, producer_model):
        if len(failed) >= max_models:
            category = _pick_category(categories) if categories else CATEGORY_BUSY
            raise LLMBusyError(
                category_message(category, f"model fallback cap: {max_models} models failed this turn"),
                category=category,
                detail="cap reached",
            ) from last_transient

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
            raise LLMBusyError(
                category_message(CATEGORY_UNKNOWN, "chat turn budget exhausted"),
                category=CATEGORY_UNKNOWN,
                detail="remaining budget too small",
            )
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
            category = error_category(exc)
            categories.add(category)
            failed.append(model)  # ONLY failures count against the per-turn cap
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
                "category": category,
                "detail": str(exc)[:200],
            }))

    if categories:
        # every model we reached failed transiently -> name the real cause
        category = _pick_category(categories)
        raise LLMBusyError(CATEGORY_MESSAGES[category], category=category,
                           detail="all models failed transiently") from last_transient

    # nothing was even attempted: the whole chain is in cooldown from earlier failures
    raise LLMBusyError(CATEGORY_MESSAGES[CATEGORY_BUSY], category=CATEGORY_BUSY,
                       detail="all models in cooldown") from last_transient
