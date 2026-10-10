"""Verify demo-mcp-notes (runs inside its pod): MCP handshake + all 3 tools.

The token is read from the environment the way the process itself sees it
(NOTES_API_TOKEN), so the script never needs the literal value on a command line.
"""

import json
import os

import httpx

BASE = "http://127.0.0.1:8000/mcp"  # loopback: default-deny NP blocks the Service IP
TOKEN = os.environ.get("NOTES_API_TOKEN", "")
H_AUTH = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-03-26",
    "Authorization": f"Bearer {TOKEN}",
}
FAILURES = []


def check(label, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {label} {detail}")
    if not cond:
        FAILURES.append(label)


def rpc(client, payload, headers=H_AUTH):
    r = client.post(BASE, json=payload, headers=headers)
    body = r.text
    return r.status_code, (json.loads(body) if body.strip() else {})


with httpx.Client(timeout=30) as c:
    check("token present in env", bool(TOKEN), f"len={len(TOKEN)}")

    status, init = rpc(
        c,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "verify-demo-notes", "version": "1"},
            },
        },
    )
    result = init.get("result", {})
    check("initialize 200 (with token)", status == 200, f"status={status}")
    check(
        "serverInfo",
        result.get("serverInfo", {}).get("name") == "demo-notes",
        json.dumps(result.get("serverInfo")),
    )

    status, _ = rpc(c, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    status, listing = rpc(c, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = {t["name"]: t for t in listing.get("result", {}).get("tools", [])}
    check("3 tools", set(tools) == {"create_note", "list_notes", "search_notes"}, f"{sorted(tools)}")
    check(
        "annotations",
        tools.get("create_note", {}).get("annotations", {}).get("readOnlyHint") is False
        and tools.get("list_notes", {}).get("annotations", {}).get("readOnlyHint") is True,
    )

    import time as _time

    marker = f"verify-{int(_time.time())}"
    status, out = rpc(
        c,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "create_note",
                    "arguments": {"title": f"Gateway demo {marker}",
                                  "body": "credential injection works"}}},
    )
    res = out.get("result", {})
    created = json.loads(res["content"][0]["text"]) if res.get("isError") is False else {}
    our_note = created.get("note", {})
    check(
        "create_note",
        res.get("isError") is False
        and our_note.get("title") == f"Gateway demo {marker}"
        and isinstance(our_note.get("id"), int),
        f"id={our_note.get('id')} title={our_note.get('title')}",
    )

    status, out = rpc(
        c,
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "list_notes", "arguments": {}}},
    )
    listing = json.loads(out["result"]["content"][0]["text"])
    our_id = str(our_note.get("id"))
    check(
        "list_notes",
        any(str(n.get("id")) == our_id for n in listing.get("notes", [])),
        f"ours (id={our_id}) listed, total={listing.get('count')}",
    )

    status, out = rpc(
        c,
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "search_notes", "arguments": {"query": marker}}},
    )
    search = json.loads(out["result"]["content"][0]["text"])
    check(
        "search_notes hit (matches our note only)",
        search.get("count") == 1 and str(search["matches"][0].get("id")) == our_id,
        f"count={search.get('count')}",
    )

    status, out = rpc(
        c,
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "search_notes", "arguments": {"query": "nothing-matches-this"}}},
    )
    check("search_notes miss", json.loads(out["result"]["content"][0]["text"])["count"] == 0)

r = httpx.get("http://127.0.0.1:8000/healthz", timeout=15)
check("probe /healthz (open)", r.status_code == 200, r.text[:70])
r = httpx.get("http://127.0.0.1:8000/readyz", timeout=15)
check("probe /readyz (token configured)", r.status_code == 200, r.text[:70])

print("=== FAILURES:", FAILURES if FAILURES else "none", "===")
raise SystemExit(1 if FAILURES else 0)
