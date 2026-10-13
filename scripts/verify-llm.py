"""Live LLM verification (runs inside gateway pod): schemas, multi-step loop, streaming.

Verifies the chat assistant against the configured LLM endpoint (Gemini's
OpenAI-compatible endpoint via gateway.llm.baseUrl/model):

   1. all 11 sanitized tool schemas are ACCEPTED (every chat completion call sends all
      tools; if any schema were rejected the call fails with an LLM error, which the
      gateway streams as text, so a clean reply proves acceptance),
   2. a multi-step tool loop works (create a product, then list orders),
   3. streaming works (SSE events arrive, then [DONE]),
   4. a wrong key yields a clear, non-secret error.

Chat calls retry with backoff: the free-tier Gemini endpoint rate-limits per-minute
requests, and the gateway streams LLM exceptions as text, so a transient 429 would
otherwise read as a failure of the thing being verified.

Run: kubectl exec -n urumi <gateway-pod> -c gateway -- python3 -c "$(cat scripts/verify-llm.py)"
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx

BASE = "http://127.0.0.1:8000"
ADMIN_EMAIL = "admin@urumi.local"
ADMIN_PASSWORD = os.environ.get("GATEWAY_ADMIN_PASSWORD", "")
FAILURES: list[str] = []

# The free-tier Gemini endpoint answers 429 for two different reasons: a per-minute rate
# limit (retrying works) and an exhausted daily quota (retrying cannot help within the
# hour). The gateway streams LLM exceptions as text (agent.py), so this script must tell
# them apart instead of blaming the thing it verifies.
RATE_MARKERS = ("rate limit", "too many requests", "throttled")
QUOTA_MARKERS = ("quota", "plan and billing", "resource_exhausted", "resource exhausted")


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"{tag}  {label} {detail}")
    if not cond:
        FAILURES.append(label)


def parse_sse_events(raw: str) -> list[dict]:
    """Parse `data: {...}\n\n` lines into a list of event dicts."""
    events = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            payload = line[6:].strip()
            if payload == "[DONE]":
                continue
            try:
                events.append(json.loads(payload))
            except Exception:
                events.append({"type": "_unparseable", "raw": payload[:200]})
    return events


def collect_text(events: list[dict]) -> str:
    return " ".join(e.get("content", "") for e in events if e.get("type") in ("token", "text")).strip()


def gw_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
    }


async def minted_or_existing_api_key() -> str:
    """Mint a fresh temp API key for the admin user (runs in-pod, so the DB is reachable)."""
    from auth.keys import create_api_key as mint_api_key
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
            raise RuntimeError("no users in DB; gateway seed did not run")
        _row, api_key = await mint_api_key(db, user.id)
        await db.commit()
        return api_key


async def main() -> int:
    if not ADMIN_PASSWORD:
        check("admin login needs GATEWAY_ADMIN_PASSWORD", False, "empty env")
        print("=== FAILURES:", FAILURES if FAILURES else "none", "===")
        return 1 if FAILURES else 0

    # A temp key for the deterministic multi-step section below (never printed).
    seen_stream = [False]
    try:
        api_key = await minted_or_existing_api_key()
    except Exception as exc:
        print(f"WARN: could not mint API key ({exc}); deterministic multi-step will be skipped")
        api_key = ""

    async with httpx.AsyncClient(base_url=BASE, timeout=90) as c:
        r = await c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, headers={"Content-Type": "application/json"})
        check("admin login -> 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200:
            print("=== FAILURES:", FAILURES if FAILURES else "none", "===")
            return 1
        cookies = r.cookies
        csrf = r.json().get("csrf_token", "")
        chat_headers = {"Content-Type": "application/json"}
        if csrf:
            chat_headers["X-CSRF-Token"] = csrf

        async def chat(content: str, tries: int = 4, delay: float = 30.0):
            """POST /api/chat/completions, retrying only on per-minute rate limits.

            The gateway streams LLM exceptions as text (agent.py), so health is judged
            from the reply, not the HTTP status. Returns (response, events, health) with
            health one of "ok", "quota" (terminal: daily quota exhausted), "error".
            """
            last_r, last_events = None, []
            for attempt in range(1, tries + 1):
                r = await c.post("/api/chat/completions", json={"messages": [{"role": "user", "content": content}]}, headers=chat_headers, cookies=cookies)
                events = parse_sse_events(r.text) if r.status_code == 200 else []
                reply = collect_text(events).lower()
                if r.status_code == 200 and "llm error" not in reply:
                    return r, events, "ok"
                if any(m in reply for m in QUOTA_MARKERS):
                    return r, events, "quota"
                if any(m in reply for m in RATE_MARKERS) and attempt < tries:
                    print(f"info: chat attempt {attempt} rate-limited; waiting {delay:.0f}s")
                    await asyncio.sleep(delay)
                    last_r, last_events = r, events
                    continue
                return r, events, "error"
            return last_r, last_events, "error"

        def quota_blocked(health: str, label: str) -> bool:
            if health == "quota":
                check(f"{label} (blocked by exhausted daily LLM quota)", False,
                      "Gemini free-tier daily quota exhausted - not a gateway failure; re-run after the daily reset or with a paid-tier key")
                return True
            return False

        # --- (1) all 11 tool schemas accepted ---
        # The chat loop sends EVERY allowed tool schema on the first LLM call. If Gemini
        # rejected any schema keyword, this call fails with an LLM error, so a clean
        # reply here proves all 11 are accepted.
        r, events, health = await chat("Reply with the single word: ok")
        if quota_blocked(health, "chat completion"):
            pass  # daily quota exhausted: nothing observable through the LLM
        else:
            ok = r.status_code == 200
            check("chat completion -> 200 (all 11 schemas accepted)", ok, f"status={r.status_code} body={r.text[:200] if not ok else ''}")
            if ok:
                types = [e.get("type") for e in events]
                check("chat streams SSE events", "token" in types or "text" in types, f"types={types[:10]}")
                # the fallback chain (ADR-029) must announce the serving model
                model_events = [e.get("model") for e in events if e.get("type") == "model"]
                check("chat emits a 'model' event (serving model)", bool(model_events), f"model_events={model_events}")
                check("chat ends with [DONE]", "[DONE]" in r.text, "no [DONE] sentinel")
                reply = collect_text(events).lower()
                # "llm timed out." / "llm error:" are yielded as text events, so the reply
                # must be non-empty AND free of error markers, not just missing "error".
                bad = not reply or "error" in reply or "timed out" in reply or "failed" in reply
                check("chat replied (no LLM error)", not bad, reply[:200])
                if ("token" in types or "text" in types) and "[DONE]" in r.text:
                    seen_stream[0] = True

        # --- (2) multi-step tool loop: create a product, then list orders ---
        # The LLM loop mechanism is exercised first (the model calls at least one tool,
        # the gateway echoes the tool results back with the Gemini thought_signature, the
        # loop iterates, and a final answer streams). Because which tool the model picks
        # first is nondeterministic, the specific create_product -> list_orders sequence
        # is then verified deterministically through the gateway's /mcp endpoint with the
        # same audited routing the chat loop uses.
        r, events, health = await chat(
            "You have tools available. Use at least one tool to inspect the store (list products, list orders, or get a product), then answer with what you found. Do not ask for more input."
        )
        if quota_blocked(health, "multi-step chat"):
            pass  # daily quota exhausted: nothing observable through the LLM
        else:
            ok = r.status_code == 200
            check("multi-step chat -> 200", ok, f"status={r.status_code} body={r.text[:200] if not ok else ''}")
            if ok:
                calls = [e for e in events if e.get("type") == "tool_call"]
                outcomes = [e.get("outcome") for e in calls]
                check("multi-step loop ran >=1 tool call", len(calls) >= 1, f"tools={[e.get('tool') for e in calls]}")
                check("all tool outcomes success", bool(calls) and all(o == "success" for o in outcomes), f"outcomes={outcomes}")
                finals = [e for e in events if e.get("type") in ("token", "text")]
                final_text = collect_text(events).lower()
                failed = not finals or "error" in final_text or "timed out" in final_text
                check("multi-step produced a final answer", not failed, final_text[:200])

        # Deterministic create -> list through /mcp (same audited router the chat loop uses).
        if not api_key:
            check("deterministic create->list needs an API key", False, "no key minted")
        else:
            hh = gw_headers(api_key)
            async with httpx.AsyncClient(base_url=BASE, timeout=60) as mc:
                await mc.post("/mcp", headers=hh, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "verify-llm", "version": "1"}}})
                await mc.post("/mcp", headers=hh, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
                mk = f"Gemini Verify {uuid.uuid4().hex[:6]}"
                cr2 = await mc.post("/mcp", headers=hh, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "woo__create_product", "arguments": {"name": mk, "regular_price": "9.99"}}})
                body2 = cr2.json() if cr2.status_code == 200 else {}
                res2 = body2.get("result", {}) if isinstance(body2, dict) else {}
                created = not bool(res2.get("isError"))
                check("mcp create_product succeeds (multi-step step 1)", created, json.dumps(body2)[:200])
                lr = await mc.post("/mcp", headers=hh, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "woo__list_orders", "arguments": {"per_page": 5}}})
                body3 = lr.json() if lr.status_code == 200 else {}
                res3 = body3.get("result", {}) if isinstance(body3, dict) else {}
                listed = not bool(res3.get("isError"))
                check("mcp list_orders succeeds after create (multi-step step 2)", listed, json.dumps(body3)[:200])

        # --- (3) streaming summary (observed on the successful chat reply above) ---
        check("streaming is SSE text/event-stream", seen_stream[0],
              "SSE token/text events ended with [DONE]" if seen_stream[0] else "no chat stream observed (quota-blocked)")

    # --- (4) wrong key -> clear error (isolated probe, in-pod, never prints the key) ---
    try:
        from config import get_settings
        from openai import AsyncOpenAI

        s = get_settings()
        bad = AsyncOpenAI(api_key="sk-wrong-key-for-llm-probe-not-the-real-one", base_url=s.openai_base_url or None)
        try:
            await bad.chat.completions.create(model=s.openai_model, messages=[{"role": "user", "content": "hi"}])
            check("wrong key -> clear LLM error", False, "unexpectedly succeeded with a bad key")
        except Exception as exc:
            msg = str(exc)[:200]
            low = str(exc).lower()
            check("wrong key -> clear LLM error", bool(msg) and ("key" in low or "401" in low or "403" in low or "unauthorized" in low or "invalid" in low), msg)
    except Exception as exc:
        check("wrong-key probe ran without crashing", False, str(exc)[:200])

    print("=== FAILURES:", FAILURES if FAILURES else "none", "===")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
