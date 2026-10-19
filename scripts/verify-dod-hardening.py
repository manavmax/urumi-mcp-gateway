"""Definition-of-Done flow with TWO users (runs INSIDE the gateway pod).

Usage (from the host, via kubectl exec like verify-gateway.py):
  python3 verify-dod-hardening.py phase1   # users + keys + mcp + revoke + disable + audit
  python3 verify-dod-hardening.py phase2   # pod-kill observation (the shell deletes the pod)

Phase 1 (admin A + member B, all through the REAL HTTP API with session + CSRF):
  admin login -> create member -> member login -> member mints API key
  -> member /mcp tools/list contains time__* -> member tool call OK
  -> admin disables the `time` server -> time__* VANISH from the member's tools/list
  -> admin re-enables -> tools return
  -> admin revokes the member key -> /mcp -> 401
  -> admin-events trail holds key.revoke + server.disable + server.enable

Phase 2 (the wrapper deletes the demo-time pod while this runs):
  poll GET /api/servers (admin session) until `time` flips Unreachable;
  while Unreachable, woo__list_orders via /mcp still works (the other upstream
  survives); then the Deployment recreates the pod and status returns Connected.

Never prints a credential: the member password is random, minted keys are
truncated to prefix...last4, cookies/CSRF are never echoed.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
ADMIN_EMAIL = "admin@urumi.local"
ADMIN_PASSWORD = os.environ.get("GATEWAY_ADMIN_PASSWORD", "")

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + label + (f": {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def mcp_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
    }


class Session:
    """One logged-in user: explicit Cookie header + CSRF token."""

    def __init__(self, email: str, password: str):
        self.email, self.password = email, password
        self.cookie = ""
        self.csrf = ""

    async def login(self, client: httpx.AsyncClient) -> bool:
        r = await client.post("/api/auth/login", json={"email": self.email, "password": self.password})
        if r.status_code != 200:
            check(f"{self.email} login", False, f"status={r.status_code}")
            return False
        self.csrf = r.json().get("csrf_token", "")
        for raw in r.headers.get_list("set-cookie"):
            if raw.startswith("urumi_session="):
                self.cookie = raw.split(";", 1)[0].split("=", 1)[1]
        return True

    def hdrs(self, *, csrf: bool = False) -> dict[str, str]:
        h = {"Cookie": f"urumi_session={self.cookie}"}
        if csrf:
            h["X-CSRF-Token"] = self.csrf
        return h


async def mint_admin_key() -> str:
    """Mint a throwaway admin API key directly in the DB (plaintext shown once)."""
    from auth.keys import create_api_key
    from db.models import User
    from db.session import get_session_factory
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as db:
        r = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        user = r.scalars().first()
        if user is None:
            raise RuntimeError("admin user not found")
        _row, raw = await create_api_key(db, user.id)
        await db.commit()
        return raw


async def tools_list(client: httpx.AsyncClient, key: str) -> list[str]:
    r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}},
                          headers=mcp_headers(key))
    if r.status_code != 200:
        return [f"__STATUS_{r.status_code}"]
    try:
        return [t.get("name", "") for t in r.json()["result"]["tools"]]
    except Exception:
        return []


async def mcp_call(client: httpx.AsyncClient, key: str, tool: str, args: dict) -> int:
    payload = {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    r = await client.post("/mcp", json=payload, headers=mcp_headers(key))
    return r.status_code


async def phase1() -> None:
    member_password = "dod-" + secrets.token_urlsafe(12)
    member_email = f"dod-member-{secrets.token_hex(4)}@urumi.local"

    async with httpx.AsyncClient(timeout=30, base_url=BASE) as c:
        # --- user A: admin ---
        admin = Session(ADMIN_EMAIL, ADMIN_PASSWORD)
        if not await admin.login(c):
            return
        check("user A (admin) login", True)

        # --- user B: member created by the admin through the real API ---
        r = await c.post("/api/users", json={"email": member_email, "password": member_password, "role": "member"},
                         headers=admin.hdrs(csrf=True))
        check("admin creates user B (member)", r.status_code == 201, f"status={r.status_code}")
        member_id = r.json().get("id", "")
        member = Session(member_email, member_password)
        await member.login(c)

        # --- member mints their own key (the real user path) ---
        r = await c.post("/api/keys", json={}, headers={**member.hdrs(csrf=True)})
        check("user B mints an API key", r.status_code == 201, f"status={r.status_code}")
        key_row = r.json()
        raw_key, key_id = key_row["key"], key_row["id"]

        # --- member /mcp works ---
        r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                       "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                                  "clientInfo": {"name": "dod", "version": "0"}}},
                         headers=mcp_headers(raw_key))
        check("user B key -> /mcp initialize", r.status_code in (200, 202), f"status={r.status_code}")
        tools = await tools_list(c, raw_key)
        check("user B tools/list works (>=8 tools)", len(tools) >= 8, f"n={len(tools)}")
        check("user B sees time__ tools", any(t.startswith("time__") for t in tools))
        code = await mcp_call(c, raw_key, "time__get_current_time", {})
        check("user B calls time__get_current_time", code == 200, f"status={code}")

        # --- admin disables the `time` upstream -> tools vanish for the member ---
        r = await c.get("/api/servers", headers={"Cookie": f"urumi_session={admin.cookie}"})
        servers = r.json().get("servers", [])
        time_srv = next((s for s in servers if s["slug"] == "time"), None)
        check("time server exists", time_srv is not None)
        if time_srv:
            r = await c.post(f"/api/servers/{time_srv['id']}/disable", headers=admin.hdrs(csrf=True))
            check("admin disables demo-time", r.status_code == 200, f"status={r.status_code}")
            tools = await tools_list(c, raw_key)
            check("time__ tools VANISH after disable", not any(t.startswith("time__") for t in tools), f"n={len(tools)}")
            r = await c.post(f"/api/servers/{time_srv['id']}/enable", headers=admin.hdrs(csrf=True))
            check("admin re-enables demo-time", r.status_code == 200, f"status={r.status_code}")
            tools = await tools_list(c, raw_key)
            check("time__ tools return after enable", any(t.startswith("time__") for t in tools), f"n={len(tools)}")

        # --- admin revokes the member key -> /mcp 401 ---
        r = await c.delete(f"/api/keys/{key_id}", headers=admin.hdrs(csrf=True))
        check("admin revokes user B's key", r.status_code == 200, f"status={r.status_code}")
        r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
                         headers=mcp_headers(raw_key))
        check("revoked key -> /mcp 401", r.status_code == 401, f"status={r.status_code}")

        # --- audit checks ---
        r = await c.get("/api/admin-events?limit=50", headers=admin.hdrs())
        actions = [e.get("action") for e in r.json().get("events", [])]
        check("admin-events: key.revoke recorded", "key.revoke" in actions)
        check("admin-events: server.disable + server.enable recorded",
              "server.disable" in actions and "server.enable" in actions)
        # The audit writer flushes on a ~1s background batch; poll briefly instead
        # of asserting on the first read.
        logs = []
        for _ in range(8):
            r = await c.get("/api/audit?limit=20", headers=member.hdrs())
            logs = r.json().get("logs", [])
            if logs:
                break
            await asyncio.sleep(1.0)
        check("audit: member sees own tool-call rows", r.status_code == 200 and len(logs) >= 1, f"rows={len(logs)}")

        # cleanup: delete the temp member (demo tenant tidy; the trail keeps its rows)
        r = await c.delete(f"/api/users/{member_id}", headers=admin.hdrs(csrf=True))
        check("cleanup: member deleted (204)", r.status_code == 204, f"status={r.status_code}")


async def phase2() -> None:
    """Pod-kill observation: the wrapper deletes the demo-time pod while this polls."""
    key = await mint_admin_key()
    if not key:
        check("phase2: temp admin key minted", False)
        return
    admin = Session(ADMIN_EMAIL, ADMIN_PASSWORD)
    async with httpx.AsyncClient(timeout=30, base_url=BASE) as c:
        await admin.login(c)

        saw_unreachable = False
        others_worked = 0
        t0 = time.monotonic()
        while time.monotonic() - t0 < 90:
            rows = (await c.get("/api/servers", headers=admin.hdrs())).json().get("servers", [])
            status = next((s.get("status") for s in rows if s["slug"] == "time"), "?")
            if status == "Unreachable":
                saw_unreachable = True
                # others must keep working DURING the outage (429 = gateway rate
                # limit, which still proves the gateway->woo path is alive)
                code = await mcp_call(c, key, "woo__list_orders", {"per_page": 1})
                if code == 200:
                    others_worked += 1
                break
            print(f"  t={round(time.monotonic() - t0, 1):>5}s time={status}")
            await asyncio.sleep(1.0)
        check("demo-time flips Unreachable after pod kill", saw_unreachable, f"t={round(time.monotonic() - t0, 1)}s")
        check("other upstream (woo) still works during the outage", others_worked >= 1, f"oks={others_worked}")
        recovered = False
        while time.monotonic() - t0 < 240:
            rows = (await c.get("/api/servers", headers=admin.hdrs())).json().get("servers", [])
            if next((s for s in rows if s["slug"] == "time"), {}).get("status") == "Connected":
                recovered = True
                break
            await asyncio.sleep(2)
        check("demo-time recovers to Connected", recovered, f"{round(time.monotonic() - t0, 1)}s total")


async def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("phase1", "phase2"):
        print("usage: verify-dod-hardening.py phase1|phase2")
        return 2
    if sys.argv[1] == "phase1":
        await phase1()
    else:
        await phase2()
    print("=== FAILURES:", FAILURES if FAILURES else "none", "===")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
