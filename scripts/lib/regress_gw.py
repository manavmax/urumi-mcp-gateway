"""Regress-core gateway checks: runs INSIDE the gateway pod (no network needed
beyond the local app; DB via the app's own session factory).

Covers the core Definition of Done with two users (admin + a throwaway member):

  phase1 <order_id>   users/keys, tools/list counts (admin vs member), the orders
                      question via MCP, disable upstream hides tools in MCP AND in
                      the chat agent's tool load, re-enable, revoke -> 401,
                      audit attribution
  during_kill         poll the time tool while its pod is deleted: other servers
                      keep working, the dashboard status leaves Connected, and
                      the tool recovers after the pod returns
  cleanup             delete the throwaway member, revoke the regress admin key,
                      remove the state file

Raw key material lives ONLY in /tmp/urumi-regress/state.json (mode 600, inside
the pod's emptyDir) for the duration of the run, is never printed, and the keys
belong to a user that cleanup deletes. The member password is random and never
printed either.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import time
from typing import Any

import httpx

BASE = "http://127.0.0.1:8000"
STATE_PATH = "/tmp/urumi-regress/state.json"
ADMIN_EMAIL = "admin@urumi.local"
REGRESS_TAG = secrets.token_hex(4)
FAILURES: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    log(f"{tag}  {label} {detail}")
    if not cond:
        FAILURES.append(label)


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as fh:
        json.dump(state, fh)
    os.chmod(STATE_PATH, 0o600)


def _load_state() -> dict:
    with open(STATE_PATH) as fh:
        return json.load(fh)


class Gateway:
    """Thin API client for one logged-in session (cookie + csrf)."""

    def __init__(self, client: httpx.Client, cookie_value: str, csrf: str):
        self.client = client
        self.headers = {"Content-Type": "application/json"}
        # explicit Cookie header: works regardless of the Secure flag (see
        # scripts/verify-llm.py for the reason)
        from config import get_settings

        self.headers["Cookie"] = f"{get_settings().session_cookie_name}={cookie_value}"
        if csrf:
            self.headers["X-CSRF-Token"] = csrf

    def req(self, method: str, path: str, body: Any = None):
        return self.client.request(method, path, json=body, headers=self.headers)


async def api_login(email: str, password: str) -> Gateway:
    client = httpx.Client(base_url=BASE, timeout=60)
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        raise RuntimeError(f"login {email} -> {r.status_code}")
    from config import get_settings

    cname = get_settings().session_cookie_name
    value = r.cookies.get(cname) or ""
    for part in r.headers.get("set-cookie", "").split(";"):
        if "=" in part and part.strip().startswith(cname + "="):
            value = part.strip().split("=", 1)[1]
    return Gateway(client, value, r.json().get("csrf_token", ""))


def mcp_post(client: httpx.Client, key: str, method: str, params: dict | None = None, msg_id: int = 1):
    payload: dict = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        payload["params"] = params
    return client.post(
        "/mcp",
        json=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        },
    )


def tool_names(client: httpx.Client, key: str) -> list[str]:
    r = mcp_post(client, key, "tools/list")
    if r.status_code != 200:
        raise RuntimeError(f"tools/list -> {r.status_code} {r.text[:120]}")
    return [t["name"] for t in r.json()["result"]["tools"]]


def call_tool(client: httpx.Client, key: str, name: str, arguments: dict | None = None):
    return mcp_post(client, key, "tools/call", {"name": name, "arguments": arguments or {}}, msg_id=int(time.time()))


async def _chat_tool_load_for(member_email: str) -> set[str]:
    """The chat agent's tool-loading code path (agent._get_allowed_tools) for the
    member - the exact function chat_loop calls; no LLM involved."""
    from chat import agent
    from db.models import User
    from db.session import get_session_factory
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as db:
        user = (await db.execute(select(User).where(User.email == member_email))).scalars().one()
        tools = await agent._get_allowed_tools(db, user)
        return {t["name"] for t in tools}


async def phase1(order_id: str) -> int:
    admin_password = os.environ.get("GATEWAY_ADMIN_PASSWORD", "")
    if not admin_password:
        log("FAIL GATEWAY_ADMIN_PASSWORD missing in pod env")
        return 1
    admin = await api_login(ADMIN_EMAIL, admin_password)
    client = admin.client

    # --- two users: admin exists; create a throwaway member ---
    member_email = f"regress-member-{REGRESS_TAG}@urumi.local"
    member_password = secrets.token_urlsafe(18)  # never printed
    r = admin.req("POST", "/api/users", {"email": member_email, "password": member_password, "role": "member"})
    check("member user created", r.status_code == 201, f"status={r.status_code}")
    if r.status_code != 201:
        return 1
    member_id = r.json()["id"]

    r = admin.req("POST", "/api/keys", {"user_id": member_id})
    check("member key minted on behalf", r.status_code == 201, f"status={r.status_code}")
    member_key = r.json().get("key", "")
    member_key_id = r.json().get("id", "")
    r = admin.req("POST", "/api/keys", {})
    check("admin regress key minted", r.status_code == 201, f"status={r.status_code}")
    admin_key = r.json().get("key", "")
    admin_key_id = r.json().get("id", "")
    if not (member_key and admin_key):
        return 1

    # --- tools/list counts for admin and member ---
    admin_tools = tool_names(client, admin_key)
    member_tools = tool_names(client, member_key)
    check(
        "tools/list returns tools for both users",
        len(admin_tools) > 0 and len(member_tools) > 0,
        f"admin={len(admin_tools)} member={len(member_tools)}",
    )
    for required in ("woo__list_orders", "woo__list_products", "time__get_current_time"):
        check(f"member sees {required}", required in member_tools, "")
        check(f"admin sees {required}", required in admin_tools, "")
    check(
        "admin and member tool counts match (default allow-all)",
        len(admin_tools) == len(member_tools),
        f"admin={len(admin_tools)} member={len(member_tools)} (deny rules present?)",
    )

    # --- the orders question via MCP, as the member ---
    r = call_tool(client, member_key, "woo__list_orders", {"per_page": 20})
    body = r.json() if r.status_code == 200 else {}
    text = "".join(b.get("text", "") for b in (body.get("result", {}).get("content") or []))
    check("member orders question via MCP -> 200", r.status_code == 200, f"status={r.status_code}")
    check(f"storefront order {order_id} visible via MCP", str(order_id) in text, "order id not in list_orders result")

    # seed an attribution row: member calls the time tool
    r = call_tool(client, member_key, "time__get_current_time", {})
    check("member time call succeeds", r.status_code == 200, f"status={r.status_code}")

    # --- disable upstream `time`: tools vanish from MCP AND the chat tool load ---
    servers = admin.req("GET", "/api/servers").json()["servers"]
    time_srv = next((s for s in servers if s["slug"] == "time"), None)
    if not time_srv:
        check("time server present", False, "no slug=time row")
        return 1
    r = admin.req("POST", f"/api/servers/{time_srv['id']}/disable")
    check("time server disabled", r.status_code == 200, f"status={r.status_code}")
    member_tools = tool_names(client, member_key)
    check("disabled upstream hidden from member tools/list", not any(t.startswith("time__") for t in member_tools),
          f"member still sees {[t for t in member_tools if t.startswith('time__')]}")
    chat_tools = await _chat_tool_load_for(member_email)
    check("disabled upstream hidden from the chat agent's tool load",
          not any(t.startswith("time__") for t in chat_tools),
          f"chat load still has {[t for t in chat_tools if t.startswith('time__')]}")
    check("enabled upstream still visible after disable", "woo__list_orders" in member_tools, "")
    r = admin.req("POST", f"/api/servers/{time_srv['id']}/enable")
    check("time server re-enabled", r.status_code == 200, f"status={r.status_code}")

    # --- revoke the member key: next call is rejected ---
    r = admin.req("DELETE", f"/api/keys/{member_key_id}")
    check("member key revoked by admin", r.status_code == 200, f"status={r.status_code}")
    r = call_tool(client, member_key, "woo__list_orders", {})
    check("revoked key rejected on next call", r.status_code == 401, f"status={r.status_code}")

    # --- audit rows under the right users ---
    # The audit writer is an async queue (batch flush ~1s), so the member's row
    # can land a moment after the call: poll for it instead of racing the flush.
    from db.models import AuditLog
    from db.models import User as U
    from db.session import get_session_factory
    from sqlalchemy import select

    factory = get_session_factory()
    member_rows: list = []
    admin_rows: list = []
    for _attempt in range(10):
        async with factory() as db:
            member = (await db.execute(select(U).where(U.email == member_email))).scalars().one()
            member_rows = (await db.execute(
                select(AuditLog).where(AuditLog.user_id == member.id, AuditLog.tool_exposed_name == "time__get_current_time")
            )).scalars().all()
            admin_user = (await db.execute(select(U).where(U.email == ADMIN_EMAIL))).scalars().one()
            admin_rows = (await db.execute(
                select(AuditLog).where(AuditLog.user_id == admin_user.id, AuditLog.tool_exposed_name == "woo__list_products")
            )).scalars().all()
        if member_rows and admin_rows:
            break
        await asyncio.sleep(1)
    check("audit row for member's time call attributed to the member", len(member_rows) >= 1,
          f"rows={len(member_rows)} outcome={[r.outcome for r in member_rows]}")
    check("audit rows exist for the admin user's calls", len(admin_rows) >= 1, f"rows={len(admin_rows)}")

    _save_state({
        "member_id": member_id,
        "member_email": member_email,
        "admin_key": admin_key,
        "admin_key_id": admin_key_id,
        "time_server_id": time_srv["id"],
        "order_id": str(order_id),
    })
    log(f"PHASE1_DONE failures={len(FAILURES)}")
    return 0 if not FAILURES else 1


async def during_kill() -> int:
    """Runs while the host deletes the demo-time pod: other servers keep
    working, the time tool goes dark, the dashboard status leaves Connected,
    and everything recovers when the pod returns."""

    state = _load_state()
    client = httpx.Client(base_url=BASE, timeout=60)
    admin_key = state["admin_key"]

    saw_failure = False
    checked_others = False
    saw_unreachable = False
    down_at = None
    deadline = time.monotonic() + 150

    async def _status_now() -> str | None:
        admin_password = os.environ.get("GATEWAY_ADMIN_PASSWORD", "")
        admin = await api_login(ADMIN_EMAIL, admin_password)
        servers = admin.req("GET", "/api/servers").json()["servers"]
        row = next((s for s in servers if s["slug"] == "time"), None)
        return row["status"] if row else None

    while time.monotonic() < deadline:
        r = call_tool(client, admin_key, "time__get_current_time", {})
        if r.status_code == 200:
            if saw_failure:
                # recovery: the status flips BACK only on the next successful
                # health probe (~one interval), so right now it may STILL be
                # Unreachable - the last chance to observe the outage marker
                if not saw_unreachable:
                    row_status = await _status_now()
                    if row_status is not None and row_status != "Connected":
                        saw_unreachable = True
                        log(f"info: dashboard time status at recovery: {row_status}")
                break
            await asyncio.sleep(1)
            continue
        if not saw_failure:
            saw_failure = True
            down_at = time.time()
            # while time is dark, the OTHER servers must keep working (asserted once)
            rw = call_tool(client, admin_key, "woo__list_products", {"per_page": 3})
            check("woo works while the time pod is down", rw.status_code == 200, f"status={rw.status_code}")
            rj = call_tool(client, admin_key, "notes__list_notes", {})
            check("notes work while the time pod is down", rj.status_code == 200, f"status={rj.status_code}")
            checked_others = True
        # and the dashboard status must leave Connected for the time server.
        # Two timing facts make a single sample flaky: (1) the passive mark
        # commits in the request dependency teardown AFTER the failing response
        # is sent, and (2) the health loop flips it within its ~5s interval.
        # So poll the status a few times per dark iteration with small sleeps.
        if not saw_unreachable:
            for _ in range(4):
                row_status = await _status_now()
                if row_status is not None and row_status != "Connected":
                    saw_unreachable = True
                    log(f"info: dashboard time status during outage: {row_status}")
                    break
                await asyncio.sleep(0.6)
        await asyncio.sleep(1.5)

    check("time tool went dark during the kill window", saw_failure, "")
    check("other upstreams stayed reachable during the kill window", checked_others, "")
    check("dashboard showed the upstream as not-Connected", saw_unreachable, "")
    if saw_failure and down_at:
        log(f"info: time tool dark at {time.strftime('%H:%M:%S', time.localtime(down_at))}")

    # recovery: time tool answers again within the bound
    deadline = time.monotonic() + 150
    recovered = False
    while time.monotonic() < deadline:
        r = call_tool(client, admin_key, "time__get_current_time", {})
        if r.status_code == 200:
            recovered = True
            break
        await asyncio.sleep(2)
    check("time tool recovered after the pod returned", recovered, "")
    log(f"PHASE2_DONE failures={len(FAILURES)}")
    return 0 if not FAILURES else 1


async def cleanup() -> int:
    state = _load_state()
    admin_password = os.environ.get("GATEWAY_ADMIN_PASSWORD", "")
    admin = await api_login(ADMIN_EMAIL, admin_password)
    r = admin.req("DELETE", f"/api/keys/{state['admin_key_id']}")
    check("regress admin key revoked", r.status_code == 200, f"status={r.status_code}")
    r = admin.req("DELETE", f"/api/users/{state['member_id']}")
    check("throwaway member deleted", r.status_code == 204, f"status={r.status_code}")
    try:
        os.remove(STATE_PATH)
        log("info: state file removed")
    except FileNotFoundError:
        pass
    log(f"CLEANUP_DONE failures={len(FAILURES)}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        log("usage: regress_gw.py phase1 <order_id> | during_kill | cleanup")
        raise SystemExit(2)
    cmd = sys.argv[1]
    rc = 2
    if cmd == "phase1" and len(sys.argv) == 3:
        rc = asyncio.run(phase1(sys.argv[2]))
    elif cmd == "during_kill":
        rc = asyncio.run(during_kill())
    elif cmd == "cleanup":
        rc = asyncio.run(cleanup())
    else:
        log("usage: regress_gw.py phase1 <order_id> | during_kill | cleanup")
        raise SystemExit(2)
    log(f"REGRESS_GATEWAY_RC={rc}")
    raise SystemExit(rc)
