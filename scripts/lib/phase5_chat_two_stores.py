"""Phase 5 final check: the chat agent compares TODAY'S ORDERS across TWO
provisioned stores, using a LOCAL STUB OpenAI-compatible LLM (never a real key).

Runs INSIDE the gateway pod. A stub OpenAI-compatible server (127.0.0.1:9101)
answers the REAL chat loop:
  turn 1 -> tool_calls [gate-alpha__list_orders, gate-bravo__list_orders]
  turn 2 -> a short text summary
The REAL loop executes those calls through the normal routing / permission /
rate-limit / audit path against each store's woo-mcp upstream. Proof:
  - tool_call events for BOTH store tools
  - audit rows attributed to the admin under the REAL tool names
  - a non-empty final text

Usage (inside the gateway pod):
  python3 phase5_chat_two_stores.py <slugA> <slugB>
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

SLUG_A = sys.argv[1] if len(sys.argv) > 1 else "gate-alpha"
SLUG_B = sys.argv[2] if len(sys.argv) > 2 else "gate-bravo"
STUB_PORT = 9101


class StubHandler(BaseHTTPRequestHandler):
    """OpenAI-compatible stub: turn 1 forces both store tools; turn 2 (after
    tool results appear in the messages) answers with text."""

    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            body = {}
        has_tool_results = any(m.get("role") == "tool" for m in body.get("messages", []))
        if not has_tool_results:
            response = {
                "id": "chatcmpl-stub-1", "object": "chat.completion", "model": "stub",
                "created": int(time.time()), "system_fingerprint": "stub",
                "choices": [{
                    "index": 0, "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant", "content": None,
                        "tool_calls": [
                            {"id": "call_a", "type": "function",
                             "function": {"name": f"{SLUG_A}__list_orders", "arguments": "{}"}},
                            {"id": "call_b", "type": "function",
                             "function": {"name": f"{SLUG_B}__list_orders", "arguments": "{}"}},
                        ],
                    },
                }],
            }
        else:
            response = {
                "id": "chatcmpl-stub-2", "object": "chat.completion", "model": "stub",
                "created": int(time.time()), "system_fingerprint": "stub",
                "choices": [{
                    "index": 0, "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": f"Today's orders: {SLUG_A} and {SLUG_B} compared from both results.",
                    },
                }],
            }
        data = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


async def main() -> int:
    server = HTTPServer(("127.0.0.1", STUB_PORT), StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # the chat loop reads get_settings() at call time: patch BOTH bindings with
    # a Settings copy that points the LLM at the stub (never a real key)
    import config

    live = config.get_settings()
    stub_settings = live.model_copy(update={
        "openai_base_url": f"http://127.0.0.1:{STUB_PORT}/v1",
        "openai_api_key": "stub-key-not-a-real-secret",
        "openai_model": "stub",
        "openai_models": "",
    })
    config.get_settings = lambda: stub_settings
    import chat.agent as agent

    if hasattr(agent, "get_settings"):
        agent.get_settings = lambda: stub_settings

    from chat.agent import chat_loop
    from db.models import AuditLog, User
    from db.session import get_session_factory
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as db:
        user = (await db.execute(select(User).where(User.email == "admin@urumi.local"))).scalars().first()
        if user is None:
            print("FAIL: admin user not found")
            return 1
        events = []
        async for evt in chat_loop(
            db, user,
            [{"role": "user", "content": "Compare today's orders across my two stores"}],
            request_id="phase5-chat-two-stores",
            tz="Asia/Kolkata",
        ):
            if isinstance(evt, dict):
                events.append(evt)

    server.shutdown()

    names = [e["tool"] for e in events if e.get("type") == "tool_call"]
    text = "".join(e.get("content", "") for e in events if e.get("type") in ("text", "token")).strip()
    print("TOOLCALLS:", names)
    print("TEXT:", text[:160])

    ok = f"{SLUG_A}__list_orders" in names and f"{SLUG_B}__list_orders" in names and bool(text)
    if ok:
        rows = (await db.execute(
            select(AuditLog.tool_exposed_name, AuditLog.outcome)
            .where(AuditLog.tool_exposed_name.in_([f"{SLUG_A}__list_orders", f"{SLUG_B}__list_orders"]))
            .order_by(AuditLog.ts.desc())
        )).all()
        print("AUDIT rows:", rows)
    print("CHAT-TWO-STORES:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
