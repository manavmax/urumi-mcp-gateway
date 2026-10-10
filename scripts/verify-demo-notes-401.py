"""Prove demo-mcp-notes rejects unauthenticated MCP requests with a proper 401.

Runs inside the pod with NO token in the request, so the outcome shows exactly what
the gateway must handle (and what an unauthenticated caller gets).
"""

import httpx

BASE = "http://127.0.0.1:8000/mcp"
FAILURES = []


def check(label, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {label} {detail}")
    if not cond:
        FAILURES.append(label)


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "no-token-check", "version": "1"},
    },
}
JSON_H = {"Content-Type": "application/json"}

cases = [
    ("no Authorization header", {}),
    ("wrong bearer token", {"Authorization": "Bearer definitely-not-the-token"}),
    ("malformed Authorization header", {"Authorization": "Basic abc123"}),
    ("bearer without a token", {"Authorization": "Bearer"}),
]

for label, headers in cases:
    r = httpx.post(BASE, json=INIT, headers=headers, timeout=20)
    check(f"{label} -> 401", r.status_code == 401, f"status={r.status_code}")
    check(f"{label} -> JSON error body", r.headers.get("content-type", "").startswith("application/json"), "")
    check(f"{label} -> WWW-Authenticate: Bearer", "bearer" in r.headers.get("www-authenticate", "").lower(),
          r.headers.get("www-authenticate", ""))

r = httpx.post(
    BASE,
    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    headers=JSON_H,
    timeout=20,
)
check("tools/list without token -> 401", r.status_code == 401, f"status={r.status_code}")

r = httpx.post(
    BASE,
    json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "list_notes", "arguments": {}}},
    headers=JSON_H,
    timeout=20,
)
check("tools/call without token -> 401", r.status_code == 401, f"status={r.status_code}")

# Probes must stay open even without a token (kubelet needs them).
r = httpx.get("http://127.0.0.1:8000/healthz", timeout=15)
check("probes stay open", r.status_code == 200, r.text[:60])

print("=== FAILURES:", FAILURES if FAILURES else "none", "===")
raise SystemExit(1 if FAILURES else 0)
