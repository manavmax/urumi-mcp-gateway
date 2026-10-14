"""In-pod LIVE reproduction: drive the real chat loop, count thought_signature 400s.

This is the faithful end-to-end path (chat.agent.chat_loop with the real DB session,
the real 11 cached tool schemas, and the real fallback chain): if the model ever omits
extra_content/google.thought_signature on a function call, the follow-up call that
echoes it is rejected by Gemini with

    400 "Function call is missing a thought_signature in functionCall parts ...
         function call default_api:X, position 2"

which the gateway currently surfaces to the user as an "LLM error (bad_request)" text
event. Run N turns and report how often that happens, with the raw error text.

Run (inside the gateway pod):

    kubectl exec -i -n urumi deploy/urumi-gateway -- python3 - < scripts/verify-thought-signature-live.py

Env: ITERATIONS (default 20), DELAY seconds between turns (default 6).
The API key/DB creds come from settings - never printed.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid

PROMPTS = [
    "List my notes (use the notes tools), then summarize them in one sentence.",
    "What orders came in today? Use the woo tools and answer from what you find.",
    "Search my notes for anything about the store and report what you find.",
    "How many products are in the store? Use a tool to check, then answer.",
    "Check the current time with the time tool, then list the first 3 orders.",
]

SIG_MARKER = "thought_signature"
RATE_MARKERS = ("rate limit", "too many requests", "throttled", "429", "exceeded your current quota")
DAILY_MARKERS = ("per day", "daily")


def _cls(text: str) -> str:
    low = text.lower()
    if SIG_MARKER in low:
        return "THOUGHT_SIGNATURE_400"
    if any(m in low for m in DAILY_MARKERS) and "per minute" not in low:
        return "QUOTA_DAILY"
    if any(m in low for m in RATE_MARKERS):
        return "RATE"
    return "OTHER"


async def main() -> int:
    iterations = int(os.environ.get("ITERATIONS", "20"))
    delay = float(os.environ.get("DELAY", "6"))

    from chat.agent import chat_loop
    from db.models import User
    from db.session import get_session_factory
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as db:
        r = await db.execute(select(User).where(User.email == "admin@urumi.local"))
        user = r.scalars().first()
        if user is None:
            r = await db.execute(select(User).limit(1))
            user = r.scalars().first()
        if user is None:
            print("FAIL no user in DB")
            return 1

    tally = {"THOUGHT_SIGNATURE_400": 0, "QUOTA_DAILY": 0, "RATE": 0, "OTHER": 0, "CLEAN": 0}
    raw: list[str] = []
    stop = False

    for i in range(1, iterations + 1):
        if stop:
            break
        prompt = PROMPTS[(i - 1) % len(PROMPTS)]
        text_parts: list[str] = []
        started = time.monotonic()
        try:
            async with factory() as db:
                r = await db.execute(select(User).where(User.email == "admin@urumi.local"))
                user = r.scalars().first()
                async for ev in chat_loop(
                    db,
                    user,
                    [{"role": "user", "content": prompt}],
                    uuid.uuid4(),
                ):
                    if ev.get("type") in ("token", "text"):
                        text_parts.append(ev.get("content", ""))
        except Exception as exc:  # chat_loop itself must not raise; record if it does
            tally["OTHER"] += 1
            line = f"turn {i:02d}: EXCEPTION {type(exc).__name__}: {str(exc)[:200]}"
            print(line)
            raw.append(line)
            await asyncio.sleep(delay)
            continue

        reply = " ".join(text_parts)
        kind = _cls(reply)
        dur = int(time.monotonic() - started)
        if kind == "CLEAN":
            tally["CLEAN"] += 1
            print(f"turn {i:02d}: clean reply ({dur}s) {reply[:90]!r}")
        else:
            tally[kind] += 1
            line = f"turn {i:02d}: {kind} ({dur}s) {reply[:400]!r}"
            print(line)
            raw.append(line)
            if kind == "QUOTA_DAILY":
                print("probe: daily quota exhausted - stop (terminal for today)")
                stop = True
        await asyncio.sleep(delay)

    print({"tally": tally, "prompt_pool": len(PROMPTS)})
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
