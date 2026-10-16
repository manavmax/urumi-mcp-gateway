"""Live observability proof (runs INSIDE the gateway pod).

Usage: python3 verify-observability-live.py <target-slug>

Drives the "plain kubectl delete pod" scenario. While the operator deletes the
target upstream's pod, this observer records once per second:
  - the target server's status + last_error_category + last_checked_at (the exact
    fields the Servers row and the banner render from - GET /api/servers reads the
    same rows),
  - whether /api/alerts reports it (banner condition),
  - that the OTHER two servers' tools keep working throughout the outage. Each
    other server is probed on a 3s cadence (the gateway API-key rate limit is
    60/min; two servers every second would 429 and look like a false outage).
    A 429 is treated as "reachable" (the gateway is up and rate-limiting us, not
    the upstream down).
and measures the Unreachable flip time and the recovery time once the new pod is
Ready. Prints a one-line-per-tick CSV so the window and latencies are visible.

Requires env already set in the gateway pod (DATABASE_URL, FERNET_KEY,
GATEWAY_ADMIN_PASSWORD). Never prints a credential.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
ADMIN_EMAIL = "admin@urumi.local"
ADMIN_PASSWORD = os.environ.get("GATEWAY_ADMIN_PASSWORD", "")
TARGET = sys.argv[1] if len(sys.argv) > 1 else "notes"
OTHERS = [s for s in ("woo", "time", "notes") if s != TARGET]
PROBE = {
    "woo": ("woo__list_products", {"per_page": 1}),
    "time": ("time__get_current_time", {}),
    "notes": ("notes__list_notes", {}),
}
PROBE_INTERVAL = 3.0  # seconds between probes of ONE other server (rate-limit safe)


def _mcp_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
    }


async def _temp_admin_key() -> tuple[str, object]:
    from auth.keys import create_api_key
    from db.models import User
    from db.session import get_session_factory
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as db:
        admin = (await db.execute(select(User).where(User.email == ADMIN_EMAIL))).scalars().first()
        if admin is None:
            raise RuntimeError(f"admin {ADMIN_EMAIL} not found")
        _row, raw = await create_api_key(db, admin.id)
        await db.commit()
        key_id = _row.id
    return raw, key_id


async def _server_row(slug: str) -> dict:
    from db.models import Server
    from db.session import get_session_factory
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as db:
        s = (await db.execute(select(Server).where(Server.slug == slug))).scalars().first()
        if s is None:
            return {}
        return {
            "status": s.status,
            "category": s.last_error_category,
            "checked": s.last_checked_at,
            "ok_at": s.last_ok_at,
            "latency_ms": s.last_latency_ms,
        }


async def _alerts(client: httpx.AsyncClient, cookie: str) -> list[str]:
    res = await client.get("/api/alerts", headers={"Cookie": f"urumi_session={cookie}"})
    if res.status_code != 200:
        return []
    return [a["slug"] for a in res.json().get("admin", [])]


async def _call(client: httpx.AsyncClient, tool: str, args: dict) -> str:
    """Return 'ok' (200), 'ratelimited' (429 -> gateway up, key limited) or 'down'."""
    res = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}},
        headers=_mcp_headers(API_KEY),
    )
    if res.status_code == 200:
        return "ok"
    if res.status_code == 429:
        return "rl"
    return f"down({res.status_code})"


API_KEY: str = ""


async def main() -> None:
    global API_KEY
    API_KEY, key_id = await _temp_admin_key()

    async with httpx.AsyncClient(base_url=BASE, timeout=httpx.Timeout(15.0)) as client:
        login = await client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        if login.status_code != 200:
            print(f"FAIL admin login: {login.status_code} {login.text[:200]}")
            return
        cookie = login.headers.get("set-cookie", "").split(";")[0].replace("urumi_session=", "")

        print(f"target={TARGET} others={OTHERS} probes={[PROBE[s][0] for s in OTHERS]} probe_interval={PROBE_INTERVAL}s")
        last_probe: dict[str, float] = {s: -99.0 for s in OTHERS}
        last_status: dict[str, str] = {s: "" for s in OTHERS}
        t0 = time.monotonic()
        prev_status = None
        flips: dict[str, float] = {}
        start = time.monotonic()
        print("t_s, target_status, category, alert?, " + ", ".join(f"{s}_res" for s in OTHERS) + ", checked_delta_s")

        while time.monotonic() - start < 240:
            now = time.monotonic()
            row = await _server_row(TARGET)
            status = row.get("status", "?")
            alerts = await _alerts(client, cookie)
            # probe each other server only when its 3s window elapses
            probes: list[str] = []
            for s in OTHERS:
                if now - last_probe[s] >= PROBE_INTERVAL:
                    last_probe[s] = now
                    last_status[s] = await _call(client, PROBE[s][0], PROBE[s][1])
                probes.append(last_status[s])
            was_unreachable = prev_status == "Unreachable"
            if prev_status is not None and status != prev_status:
                flips.setdefault(status, now - t0)
            prev_status = status
            checked_delta = ""
            if row.get("checked"):
                checked_delta = f"{max(0, round(now - row['checked'].timestamp()))}s"
            print(
                f"{round(now - t0, 1)}, {status}, {row.get('category')}, "
                f"{'Y' if TARGET in alerts else 'n'}, " + ", ".join(probes) + f", {checked_delta}",
                flush=True,
            )
            if status == "Connected" and was_unreachable:
                break
            await asyncio.sleep(1.0)

        print("flip_times_s:", flips)
        from auth.keys import revoke_api_key
        from db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as db:
            await revoke_api_key(db, key_id)
            await db.commit()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
