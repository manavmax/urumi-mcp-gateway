"""One-off LLM model probe (NOT run at startup, not part of `make test`).

Answers one question per model, with a real request and a real tool:

    "If the gateway calls this model, does the endpoint accept it, and can it
     call a tool?"

Usage (the key comes from the environment only - never from a file, and it is
never printed):

    OPENAI_API_KEY=... .venv/bin/python scripts/check-models.py gemini-3.8-flash gemini-3.5-flash

One dummy tool ("ping") is attached to every request so a model that cannot use
tools is distinguishable from one that answered in plain text. max_tokens is a
NORMAL value (default 256, not 1): some endpoints validate the budget against
the tool-call shape, so a 1-token probe would report failures that never happen
in production.

Output is one line per model and nothing else:

    <model>  http=<status>  tool_call=<yes|no|n/a>  category=<...>

Category vocabulary (deliberately small and status-driven):

    200              -> "ok"
    401 / 403        -> "auth"
    404              -> "not-found"
    400 / 422        -> "bad-request"  (refined to "not-found" / "quota" only
                                      when the response text says so)
    429 / 5xx        -> "unknown"

429 and 5xx are ALWAYS "unknown", never "unsupported" (and never "not-found"):
a rate-limited, quota-exhausted or overloaded endpoint says nothing about the
model name itself, so this probe must not be read as "this model does not
exist". Use --verbose to see the short response text behind a category.

3 seconds separate consecutive models so one probe cannot trip the endpoint's
per-minute rate limit and poison the next model's result.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# A dummy tool: the point is whether the model CAN emit a tool call, not what it
# would do. "ping" carries no arguments so a model that echoes arguments wrongly
# is not penalised by schema validation.
DUMMY_TOOL = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Return the string pong. Use this to confirm tool calling works.",
        "parameters": {"type": "object", "properties": {}},
    },
}

PROMPT = "Call the ping tool once, then reply with the single word ok."

NOT_FOUND_MARKERS = (
    "is not found for api version",
    "model not found",
    "models/",
    "does not exist",
    "unknown model",
    "not supported",  # an endpoint refusing the NAME, not overload
)
QUOTA_MARKERS = ("quota", "resource_exhausted", "resource exhausted", "billing")


def categorize(status: int, body: str) -> str:
    """Map (HTTP status, response text) to one of: ok / auth / not-found /
    bad-request / quota / unknown.

    429 and every 5xx are "unknown" by design: they are transient and say
    nothing about whether the model exists or supports tools.
    """
    low = body.lower()
    if 200 <= status < 300:
        return "ok"
    if status in (401, 403):
        # an auth-shaped failure that talks about quota is a quota failure
        if any(m in low for m in QUOTA_MARKERS):
            return "quota"
        return "auth"
    if status == 404:
        return "not-found"
    if status == 429 or 500 <= status <= 599:
        return "unknown"
    if status in (400, 422):
        if any(m in low for m in NOT_FOUND_MARKERS):
            return "not-found"
        if any(m in low for m in QUOTA_MARKERS):
            return "quota"
        return "bad-request"
    return "unknown"


def service_error_text(body: str) -> str:
    """Short, secret-free description of an error body (never the request)."""
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip().replace("\n", " ")[:120]
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err)[:120]
    if isinstance(err, str):
        return err[:120]
    return body.strip().replace("\n", " ")[:120]


async def probe(client: httpx.AsyncClient, model: str, max_tokens: int):
    """Send ONE chat completion with one dummy tool. Never raises."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "tools": [DUMMY_TOOL],
        "tool_choice": "auto",
        "max_tokens": max_tokens,
    }
    try:
        r = await client.post("/chat/completions", json=payload)
    except httpx.HTTPError as exc:
        return {"model": model, "http": type(exc).__name__, "tool_call": "n/a",
                "category": "unknown", "detail": service_error_text(str(exc))}
    body = r.text
    if r.status_code >= 200 and r.status_code < 300:
        tool_call = "n/a"
        try:
            data = json.loads(body) if body.strip() else {}
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            tool_call = "yes" if msg.get("tool_calls") else "no"
        except (ValueError, TypeError, KeyError, IndexError):
            tool_call = "n/a"
        return {"model": model, "http": r.status_code, "tool_call": tool_call,
                "category": "ok", "detail": ""}
    return {"model": model, "http": r.status_code, "tool_call": "n/a",
            "category": categorize(r.status_code, body),
            "detail": service_error_text(body)}


async def run(models: list[str], args) -> int:
    if not args.base_url:
        print("error: no base URL (set OPENAI_BASE_URL or pass --base-url)", file=sys.stderr)
        return 2
    if not args.api_key:
        print("error: OPENAI_API_KEY is empty - export it in this shell (the probe never reads a file)", file=sys.stderr)
        return 2

    headers = {"Authorization": f"Bearer {args.api_key}", "Content-Type": "application/json"}
    any_ok = False
    async with httpx.AsyncClient(base_url=args.base_url, headers=headers, timeout=args.timeout) as client:
        for i, model in enumerate(models):
            res = await probe(client, model, args.max_tokens)
            if res["category"] == "ok":
                any_ok = True
            print(f"{res['model']}  http={res['http']}  tool_call={res['tool_call']}  category={res['category']}")
            if args.verbose and res["detail"]:
                print(f"    detail: {res['detail']}")
            if i < len(models) - 1:
                await asyncio.sleep(args.sleep)
    return 0 if any_ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description="Probe LLM models for HTTP status, tool-call support and error category.")
    p.add_argument("models", nargs="+", help="model names to probe, in the order given")
    p.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL,
                   help="OpenAI-compatible base URL (default: $OPENAI_BASE_URL or the Gemini endpoint)")
    p.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""),
                   help="API key (default: $OPENAI_API_KEY); never printed")
    p.add_argument("--max-tokens", type=int, default=256, help="normal completion budget (default 256, NOT 1)")
    p.add_argument("--sleep", type=float, default=3.0, help="seconds between models (default 3)")
    p.add_argument("--timeout", type=float, default=60.0, help="per-request timeout in seconds (default 60)")
    p.add_argument("--verbose", action="store_true", help="also print a short response detail per model")
    args = p.parse_args()
    return asyncio.run(run(args.models, args))


if __name__ == "__main__":
    raise SystemExit(main())
