"""Phase 4 replica-resilience probe (host-side, through the kind ingress).

Drives one MCP "session" (same key, sequential calls) through the gateway
Service while the orchestrator deletes one of the two gateway replicas. After
the loop it verifies, inside the gateway pod's DB, that the audit trail has
NO duplicate request_ids and exactly one row per successful call (no gaps).

Runs from the HOST against the ingress (dashboard.127.0.0.1.nip.io) - the same
path real clients take - because the gateway's own default-deny egress policy
(correctly) forbids in-pod calls to its own Service VIP.

usage: replica_probe.py calls <count>            # host-side loop
       replica_probe.py audit <since-iso> <expected-successes>  # in-POD check

env: GATEWAY_ADMIN_PASSWORD (from the gateway-admin Secret; never printed),
     PROBE_BASE (default http://localhost), PROBE_HOST (ingress Host header).
"""

from __future__ import annotations

import asyncio
import os
import sys

BASE = os.environ.get("PROBE_BASE", "http://localhost")
HOST_HEADER = os.environ.get("PROBE_HOST", "dashboard.127.0.0.1.nip.io")


async def calls(count: int) -> int:
    import httpx

    async with httpx.AsyncClient(base_url=BASE, timeout=30, headers={"Host": HOST_HEADER}) as c:
        r = await c.post("/api/auth/login", json={"email": "admin@urumi.local", "password": os.environ["GATEWAY_ADMIN_PASSWORD"]})
        assert r.status_code == 200, f"login {r.status_code}"
        csrf = r.json()["csrf_token"]
        r = await c.post("/api/keys", json={}, headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"})
        key = r.json()["key"]
        kid = r.json()["id"]
        print(f"probe key minted id={kid}", flush=True)

        mh = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "MCP-Protocol-Version": "2025-03-26"}
        ok = fail = 0
        for i in range(count):
            r = await c.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "time__get_current_time", "arguments": {}}},
                headers=mh,
            )
            if r.status_code == 200:
                ok += 1
            else:
                fail += 1
            print(f"call {i}: {r.status_code}", flush=True)
            await asyncio.sleep(1)
        # revoke the probe key
        await c.delete(f"/api/keys/{kid}", headers={"X-CSRF-Token": csrf})
        print(f"SUMMARY ok={ok} fail={fail}", flush=True)
        return 0 if fail == 0 else 1


async def audit(since_iso: str, expected: int) -> int:
    from datetime import datetime

    from db.session import get_session_factory
    from sqlalchemy import text

    since = datetime.fromisoformat(since_iso)
    factory = get_session_factory()
    async with factory() as db:
        rows = (await db.execute(text(
            "SELECT request_id, outcome FROM audit_logs "
            "WHERE tool_exposed_name = 'time__get_current_time' AND ts >= :since ORDER BY id"
        ), {"since": since})).all()
    outcomes = [r[1] for r in rows]
    ids = [str(r[0]) for r in rows]
    dupes = len(ids) - len(set(ids))
    successes = outcomes.count("success")
    print(f"AUDIT rows={len(rows)} successes={successes} dupes={dupes} expected_successes={expected}")
    assert dupes == 0, f"DUPLICATE audit request_ids: {dupes}"
    assert successes == expected, f"audit gaps: {successes} rows != {expected} successful calls"
    assert len(rows) == successes, "non-success rows in the probe window"
    print("AUDIT OK: no duplicates, no gaps")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("calls", "audit"):
        print("usage: replica_probe.py calls <count> | audit <since-iso> <expected-successes>")
        raise SystemExit(2)
    if sys.argv[1] == "calls":
        raise SystemExit(asyncio.run(calls(int(sys.argv[2]))))
    raise SystemExit(asyncio.run(audit(sys.argv[2], int(sys.argv[3]))))
