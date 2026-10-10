"""Verify woo-mcp (runs inside its pod): MCP handshake, the 6 tools, error mapping.

Every assertion names the code it expects. In particular the negative cases assert the
SPECIFIC Woo error code, not just `isError:true` — a stricter version of these checks is
what caught a stale Consumer Key (Woo answers 401 for every call, so a loose
"isError == True" check would still have passed).

Also asserts a positive authenticated call first, so a run can never succeed on 401s.
"""

import json
import time

import httpx

BASE = "http://127.0.0.1:8000/mcp"  # loopback: default-deny NP blocks the Service IP
H = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-03-26",
}
FAILURES = []


def check(label, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {label} {detail}")
    if not cond:
        FAILURES.append(label)


def rpc(client, payload):
    r = client.post(BASE, json=payload, headers=H)
    body = r.text
    return r.status_code, (json.loads(body) if body.strip() else {})


def tool_text(result):
    """First text block of a tools/call result ('' when absent)."""

    return (result.get("content") or [{}])[0].get("text", "")


with httpx.Client(timeout=30) as c:
    status, init = rpc(
        c,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "verify-mcp", "version": "1"},
            },
        },
    )
    result = init.get("result", {})
    check("initialize 200", status == 200, f"status={status}")
    check(
        "serverInfo",
        result.get("serverInfo", {}).get("name") == "woo-mcp",
        json.dumps(result.get("serverInfo")),
    )
    check(
        "protocolVersion 2025-03-26",
        result.get("protocolVersion") == "2025-03-26",
        result.get("protocolVersion", ""),
    )

    status, _ = rpc(c, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    check("initialized 202", status == 202, f"status={status}")

    status, listing = rpc(c, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = {t["name"]: t for t in listing.get("result", {}).get("tools", [])}
    expected = {
        "list_products",
        "get_product",
        "create_product",
        "list_orders",
        "get_order",
        "update_order_status",
    }
    check("6 tools", set(tools) == expected, f"{sorted(tools)}")
    check(
        "readOnly annotations",
        tools.get("list_products", {}).get("annotations", {}).get("readOnlyHint") is True
        and tools.get("create_product", {}).get("annotations", {}).get("readOnlyHint") is False,
    )

    # --- positive control: an authenticated read must actually return data -----------
    # Without this, a cluster with a stale key would look "green" on the error checks.
    status, out = rpc(
        c,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_products", "arguments": {"per_page": 1}},
        },
    )
    res = out.get("result", {})
    text = tool_text(res)
    check("list_products authenticated (not isError)", res.get("isError") is False, text[:100])
    check(
        "list_products returns a product list",
        isinstance(json.loads(text).get("products", None) if text else None, list)
        and "WOO_" not in text,
        text[:100],
    )

    # --- write path ------------------------------------------------------------------
    sku = f"VERIFY-{int(time.time())}"
    status, out = rpc(
        c,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "create_product",
                "arguments": {"name": "Verify Tee", "regular_price": "12.34", "sku": sku},
            },
        },
    )
    res = out.get("result", {})
    text = tool_text(res)
    check("create_product ok", res.get("isError") is False and '"created":true' in text, text[:110])
    new_id = json.loads(text).get("id") if text else None
    check(
        "create_product returned an id",
        isinstance(new_id, int) and new_id > 0,
        f"id={new_id}",
    )

    status, out = rpc(
        c,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "get_product", "arguments": {"id": new_id}},
        },
    )
    res = out.get("result", {})
    text = tool_text(res)
    check(
        "get_product round trip (reads back what we created)",
        res.get("isError") is False and str(new_id) in text,
        text[:110],
    )

    status, out = rpc(
        c,
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "list_orders", "arguments": {"per_page": 1}},
        },
    )
    res = out.get("result", {})
    text = tool_text(res)
    check(
        "list_orders authenticated",
        res.get("isError") is False and '"orders"' in text and "WOO_" not in text,
        text[:110],
    )

    # --- negative cases must assert the SPECIFIC code ---------------------------------
    status, out = rpc(
        c,
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "get_product", "arguments": {"id": 987654321}},
        },
    )
    res = out.get("result", {})
    text = tool_text(res)
    check(
        "unknown product -> WOO_NOT_FOUND (and not an auth error)",
        res.get("isError") is True
        and "WOO_NOT_FOUND" in text
        and "WOO_AUTH_FAILED" not in text,
        text[:110],
    )

    status, out = rpc(
        c,
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "update_order_status", "arguments": {"id": 987654321, "status": "completed"}},
        },
    )
    res = out.get("result", {})
    text = tool_text(res)
    check(
        "unknown order -> WOO_NOT_FOUND (not WOO_BAD_REQUEST)",
        res.get("isError") is True and "WOO_NOT_FOUND" in text and "WOO_BAD_REQUEST" not in text,
        text[:110],
    )

    status, out = rpc(
        c,
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "create_product",
                "arguments": {"name": "dupe", "regular_price": "1.00", "sku": sku},
            },
        },
    )
    res = out.get("result", {})
    text = tool_text(res)
    check(
        "duplicate SKU -> WOO_BAD_REQUEST",
        res.get("isError") is True and "WOO_BAD_REQUEST" in text,
        text[:110],
    )

    status, out = rpc(
        c,
        {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
         "params": {"name": "does_not_exist", "arguments": {}}},
    )
    res = out.get("result", {})
    check(
        "unknown tool -> isError with 'Unknown tool'",
        res.get("isError") is True and "Unknown tool" in tool_text(res),
        tool_text(res)[:80],
    )

r = httpx.get("http://127.0.0.1:8000/healthz", timeout=15)
check("probe /healthz", r.status_code == 200, r.text[:60])
r = httpx.get("http://127.0.0.1:8000/readyz", timeout=15)
check("probe /readyz (Woo reachable)", r.status_code == 200, r.text[:70])

print("=== FAILURES:", FAILURES if FAILURES else "none", "===")
raise SystemExit(1 if FAILURES else 0)
