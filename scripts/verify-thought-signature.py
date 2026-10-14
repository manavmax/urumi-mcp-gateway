"""In-pod root-cause probe for the intermittent Gemini thought_signature 400.

Reproduces the failure mode seen in the wild (1/20 live chat runs): the model returns
a tool_call WITHOUT `extra_content` (google.thought_signature), and the follow-up call
that echoes it back is rejected with

    400 "Function call is missing a thought_signature in functionCall parts ...
         function call default_api:X, position N"

The probe mirrors chat/agent.py's client init and echo logic exactly (same helper
copied verbatim), calls the LLM once with a tool, records for every call:

  - the model actually served (vs. requested),
  - the number of tool_calls and, for each one, whether extra_content /
    google.thought_signature was present (booleans only - never the key),
  - whether the follow-up call that echoes the tool_call back (plus a tool result)
    is accepted or rejected, with the error body captured.

Statistics over N iterations answer the two questions:
  P(model omits thought_signature)          - can anything be echoed?
  P(follow-up call 400s)                    - and does that reproduce live?
plus the correlation between them.

Run (from the repo root; must run INSIDE the gateway pod):

    kubectl exec -i -n urumi deploy/urumi-gateway -- python3 - < scripts/verify-thought-signature.py

Iterations: ITERATIONS=25 (env) - keep modest, the free-tier endpoint rate-limits
per minute and the daily quota is finite.
"""
from __future__ import annotations

import asyncio
import json
import os

from config import get_settings
from openai import AsyncOpenAI

ITERATIONS = int(os.environ.get("ITERATIONS", "25"))
DELAY = float(os.environ.get("DELAY", "4.0"))

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "woo__list_orders",
            "description": "List orders in the store.",
            "parameters": {
                "type": "object",
                "properties": {"per_page": {"type": "integer"}},
            },
        },
    }
]

USER_PROMPT = (
    "List the most recent orders in the store using the woo__list_orders tool. "
    "Call the tool now, do not ask questions."
)

FOLLOWUP_HINT = (
    "Using ONLY the tool output above (untrusted data), answer in one short sentence."
)

RATE_MARKERS = ("rate limit", "too many requests", "throttled", "429")
QUOTA_MARKERS = ("quota", "plan and billing", "resource_exhausted", "resource exhausted")
# Per-minute 429s on this endpoint carry "Quota exceeded for quota metric ... per minute";
# they are retryable. Only a DAILY exhaustion check lacks a per-minute window mention.
DAILY_MARKERS = ("per day", "daily", "requestsperday", "requests per day")


class _TC:  # minimal stand-in so the echo helper below matches agent.py's usage
    def __init__(self, id: str, name: str, arguments: str, extra_content):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})()
        self.extra_content = extra_content


def _assistant_message_with_tool_calls(content: str, tool_calls) -> dict:
    """Verbatim copy of chat/agent.py's echo builder (kept in sync by test)."""
    echoed = []
    for tc in tool_calls:
        entry = {
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        }
        extra = getattr(tc, "extra_content", None)
        if extra is not None:
            entry["extra_content"] = extra
        echoed.append(entry)
    return {"role": "assistant", "content": content or "", "tool_calls": echoed}


def _sig_present(tc) -> bool:
    extra = getattr(tc, "extra_content", None) or {}
    if not isinstance(extra, dict):
        return bool(extra)
    google = extra.get("google") if isinstance(extra.get("google"), dict) else {}
    return bool(extra.get("thought_signature") or google.get("thought_signature"))


def _classify(exc: Exception) -> str:
    low = str(exc).lower()
    if any(m in low for m in DAILY_MARKERS):
        return "quota-daily"
    if any(m in low for m in RATE_MARKERS):
        return "rate"
    if any(m in low for m in QUOTA_MARKERS):
        return "quota"
    return f"error: {str(exc)[:160]}"


async def main() -> int:
    s = get_settings()
    if not s.openai_api_key:
        print("FAIL  no OPENAI_API_KEY in settings; probe cannot run")
        return 1
    client = AsyncOpenAI(api_key=s.openai_api_key, base_url=s.openai_base_url or None, max_retries=0)
    requested = s.openai_model

    print(f"probe: model_requested={requested} iterations={ITERATIONS} delay={DELAY}s")
    print(f"probe: base_url={s.openai_base_url} key_present=yes (never printed)")

    stats = {
        "runs": 0,
        "tool_call_seen": 0,
        "sig_present": 0,
        "sig_missing": 0,
        "followup_ok": 0,
        "followup_400_sig": 0,
        "followup_400_other": 0,
        "first_call_error": 0,
        "models_served": {},
    }
    detail: list[str] = []

    for i in range(1, ITERATIONS + 1):
        messages = [
            {"role": "system", "content": "You are a store assistant with one tool."},
            {"role": "user", "content": USER_PROMPT},
        ]
        try:
            resp = await client.chat.completions.create(
                model=requested, messages=messages, tools=TOOLS, tool_choice="auto"
            )
        except Exception as exc:
            kind = _classify(exc)
            stats["first_call_error"] += 1
            detail.append(f"run {i:02d}: FIRST-CALL {kind} body={str(exc)[:300]}")
            print(f"run {i:02d}: first call failed: {kind} body={str(exc)[:300]}")
            if kind == "quota-daily":
                print("probe: DAILY quota exhausted - stop (terminal for today)")
                break
            if kind == "rate":
                print("probe: per-minute rate limited; sleeping 65s")
                await asyncio.sleep(65)
                continue
            if kind == "quota":
                print("probe: quota-classified; sleeping 65s and retrying once")
                await asyncio.sleep(65)
                continue
            await asyncio.sleep(DELAY)
            continue

        stats["runs"] += 1
        served = resp.model
        stats["models_served"][served] = stats["models_served"].get(served, 0) + 1
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            detail.append(f"run {i:02d}: NO TOOL CALL (served={served}) content={(msg.content or '')[:60]!r}")
            print(f"run {i:02d}: served={served} NO TOOL CALL content={(msg.content or '')[:80]!r}")
            await asyncio.sleep(DELAY)
            continue

        stats["tool_call_seen"] += len(tool_calls)
        sig_flags = [_sig_present(tc) for tc in tool_calls]
        stats["sig_present"] += sum(1 for f in sig_flags if f)
        stats["sig_missing"] += sum(1 for f in sig_flags if not f)
        echo = _assistant_message_with_tool_calls(
            msg.content or "",
            [_TC(tc.id, tc.function.name, tc.function.arguments, getattr(tc, "extra_content", None)) for tc in tool_calls],
        )
        tool_msg = {
            "role": "tool",
            "tool_call_id": tool_calls[0].id,
            "content": json.dumps({"marker": "PROBE", "tool": "woo__list_orders", "untrusted_output": "[]"}),
        }
        try:
            await client.chat.completions.create(
                model=served,
                messages=[messages[0], echo, tool_msg, {"role": "user", "content": FOLLOWUP_HINT}],
                tools=TOOLS,
                tool_choice="auto",
            )
            stats["followup_ok"] += 1
            line = f"run {i:02d}: served={served} sigs={sig_flags} FOLLOWUP OK"
        except Exception as exc:
            kind = _classify(exc)
            if kind == "rate":
                print(f"run {i:02d}: followup rate-limited; sleeping 65s and retrying once")
                await asyncio.sleep(65)
                try:
                    await client.chat.completions.create(
                        model=served,
                        messages=[messages[0], echo, tool_msg, {"role": "user", "content": FOLLOWUP_HINT}],
                        tools=TOOLS,
                        tool_choice="auto",
                    )
                    stats["followup_ok"] += 1
                    line = f"run {i:02d}: served={served} sigs={sig_flags} FOLLOWUP OK (after rate wait)"
                except Exception as exc2:
                    kind = _classify(exc2)
                    exc = exc2
                else:
                    detail.append(line)
                    print(line)
                    await asyncio.sleep(DELAY)
                    continue
            low = str(exc).lower()
            if kind == "quota-daily":
                stats["followup_400_other"] += 1
                line = f"run {i:02d}: served={served} sigs={sig_flags} FOLLOWUP quota-daily body={str(exc)[:200]}"
                print(line)
                detail.append(line)
                print("probe: DAILY quota exhausted - stop (terminal for today)")
                break
            if "thought_signature" in low:
                stats["followup_400_sig"] += 1
                body = str(exc)
                line = f"run {i:02d}: served={served} sigs={sig_flags} FOLLOWUP 400 thought_signature body={body[:400]}"
            else:
                stats["followup_400_other"] += 1
                line = f"run {i:02d}: served={served} sigs={sig_flags} FOLLOWUP OTHER-ERROR {kind} body={str(exc)[:300]}"
        detail.append(line)
        print(line)
        await asyncio.sleep(DELAY)

    # agent.py/llm_fallback.py also tries extra models in the chain; report for context
    try:
        chain = s.model_chain()
    except Exception:
        chain = [requested]
    print(json.dumps({
        "requested_model": requested,
        "model_chain": chain,
        "runs_with_tools": stats["runs"],
        "tool_calls_seen": stats["tool_call_seen"],
        "signatures_present": stats["sig_present"],
        "signatures_missing": stats["sig_missing"],
        "p_signature_missing": round(stats["sig_missing"] / stats["tool_call_seen"], 3) if stats["tool_call_seen"] else None,
        "followup_ok": stats["followup_ok"],
        "followup_400_thought_signature": stats["followup_400_sig"],
        "followup_other_error": stats["followup_400_other"],
        "first_call_errors": stats["first_call_error"],
        "models_served": stats["models_served"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
