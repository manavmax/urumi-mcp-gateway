"""Verify demo-mcp-time (runs inside its pod): MCP handshake, both tools, error paths."""

import json

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
                "clientInfo": {"name": "verify-demo-time", "version": "1"},
            },
        },
    )
    result = init.get("result", {})
    check("initialize 200", status == 200, f"status={status}")
    check(
        "serverInfo",
        result.get("serverInfo", {}).get("name") == "demo-time",
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
    check("2 tools", set(tools) == {"get_current_time", "convert_time"}, f"{sorted(tools)}")
    check(
        "readOnly annotations",
        tools.get("get_current_time", {}).get("annotations", {}).get("readOnlyHint") is True,
    )

    status, out = rpc(
        c,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "get_current_time", "arguments": {}}},
    )
    res = out.get("result", {})
    payload = json.loads(res["content"][0]["text"]) if res.get("isError") is False else {}
    check("get_current_time", res.get("isError") is False and "now_utc" in payload,
          payload.get("now_utc", "")[:30])

    status, out = rpc(
        c,
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "get_current_time", "arguments": {"timezone_name": "Europe/Berlin"}}},
    )
    payload = json.loads(out["result"]["content"][0]["text"])
    check("get_current_time(timezone)", payload.get("timezone") == "Europe/Berlin", payload.get("now_local", ""))

    status, out = rpc(
        c,
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "get_current_time", "arguments": {"timezone_name": "Not/AZone"}}},
    )
    res = out.get("result", {})
    text = (res.get("content") or [{}])[0].get("text", "")
    check("bad timezone -> isError", res.get("isError") is True and "Unknown timezone" in text, text[:90])

    status, out = rpc(
        c,
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "convert_time",
                    "arguments": {"time": "2026-10-10T14:30:00", "from_tz": "UTC", "to_tz": "Asia/Kolkata"}}},
    )
    res = out.get("result", {})
    converted = json.loads(res["content"][0]["text"]) if res.get("isError") is False else {}
    check("convert_time", res.get("isError") is False and converted.get("to_timezone") == "Asia/Kolkata",
          converted.get("to_local", ""))

    status, out = rpc(
        c,
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
         "params": {"name": "convert_time",
                    "arguments": {"time": "not-a-date", "from_tz": "UTC", "to_tz": "UTC"}}},
    )
    res = out.get("result", {})
    text = (res.get("content") or [{}])[0].get("text", "")
    check("bad datetime -> isError", res.get("isError") is True and "Invalid datetime" in text, text[:90])

r = httpx.get("http://127.0.0.1:8000/healthz", timeout=15)
check("probe /healthz", r.status_code == 200, r.text[:60])
r = httpx.get("http://127.0.0.1:8000/readyz", timeout=15)
check("probe /readyz", r.status_code == 200, r.text[:60])

print("=== FAILURES:", FAILURES if FAILURES else "none", "===")
raise SystemExit(1 if FAILURES else 0)
