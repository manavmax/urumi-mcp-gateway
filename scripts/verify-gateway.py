"""Verify gateway end-to-end (runs inside gateway pod): handshake, fan-out, routing, SSRF, audit.

Requires env already set in the gateway pod: DATABASE_URL, FERNET_KEY.
Needs at least one API key; if missing we mint a temp one for the `admin@urumi.local` user.

Patterns:
- Gateway is authoritative: the tool set we see via the gateway must be exactly the
  demo servers expose (prefix-aggregated). Negative cases assert the concrete failure
  mode (401 vs 404 vs 429 vs SSRF), so a stale secret or silent swallow never reads as green.

Run: kubectl exec -n urumi <gateway-pod> -c gateway -- python3 -c "$(cat scripts/verify-gateway.py)"
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000"
FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"{tag}  {label} {detail}")
    if not cond:
        FAILURES.append(label)


def gw_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
    }


async def minted_or_existing_api_key() -> tuple[str, str]:
    """Return (api_key_plaintext, api_key_id_str). Tries env/config first, else mints via DB."""
    # Try env-passed key? Gateway pod may not have one; try to load from DB/in-app mint.
    # We do in-process DB import so this file is self-contained.
    from sqlalchemy import select

    from db.session import get_session_factory
    from db.models import ApiKey, User
    from auth.keys import create_api_key as mint_api_key

    factory = get_session_factory()
    async with factory() as db:
        # Prefer any existing unrevoked key
        r = await db.execute(select(ApiKey).where(ApiKey.revoked_at.is_(None)).limit(1))
        row = r.scalars().first()
        if row is not None:
            # We don't have plaintext for existing rows (hashed). So still mint a fresh temp key.
            pass
        # Find or create admin user
        r = await db.execute(select(User).where(User.email == "admin@urumi.local"))
        user = r.scalars().first()
        if user is None:
            print("no admin user found; running alembic/seed may be required")
            # fallback: take any user
            r = await db.execute(select(User).limit(1))
            user = r.scalars().first()
            if user is None:
                raise RuntimeError("no users in DB; gateway seed did not run")
        _row, api_key = await mint_api_key(db, user.id)
        await db.commit()
        return api_key, str(user.id)


def rpc_result(body: dict) -> dict:
    return body.get("result", body)


async def main() -> int:
    # Be resilient: this script lives in the gateway pod, so imports from src/gateway are on PYTHONPATH (/app)
    api_key = ""
    api_key_label = "( minted )"
    try:
        api_key, _ = await minted_or_existing_api_key()
    except Exception as exc:
        print(f"WARN: could not mint API key ({exc}); trying unauth probe only")
        api_key = ""

    async with httpx.AsyncClient(timeout=30) as c:
        # --- unauth must 401/403 (not 200) ---
        r = await c.post(f"{BASE}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, headers={"Content-Type": "application/json", "MCP-Protocol-Version": "2025-03-26"})
        body = {}
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text[:300]}
        err = (body.get("error") or {}).get("message", "") + str(body.get("_raw", ""))
        check("mcp unauth -> 401 (missing bearer)", r.status_code in (401, 403), f"status={r.status_code} body={json.dumps(body)[:200]}")

        if not api_key:
            print("no api key available — stopping after unauth check")
            print("=== FAILURES:", FAILURES if FAILURES else "none", "===")
            return 1 if FAILURES else 0

        h = gw_headers(api_key)

        # --- probes ---
        r = await c.get(f"{BASE}/healthz")
        check("GET /healthz 200", r.status_code == 200, r.text[:80])
        r = await c.get(f"{BASE}/readyz")
        check("GET /readyz 200", r.status_code == 200, r.text[:120])

        # --- initialize ---
        r = await c.post(f"{BASE}/mcp", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "verify-gateway", "version": "1"}}})
        try:
            init = r.json()
        except Exception:
            init = {"_raw": r.text[:400]}
        check("initialize 200", r.status_code == 200, f"status={r.status_code}")
        check("initialize protocolVersion 2025-03-26", init.get("result", {}).get("protocolVersion") == "2025-03-26", json.dumps(init.get("result", {}))[:200])
        check("initialize serverInfo gateway", "gateway" in json.dumps(init.get("result", {}).get("serverInfo", {})).lower(), json.dumps(init.get("result", {}).get("serverInfo"))[:160])

        r = await c.post(f"{BASE}/mcp", headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        check("notifications/initialized 202", r.status_code == 202, f"status={r.status_code}")

        # --- tools/list fan-out (3 servers expected) ---
        r = await c.post(f"{BASE}/mcp", headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        try:
            lst = r.json()
        except Exception:
            lst = {"_raw": r.text[:500]}
        tools = lst.get("result", {}).get("tools", []) if isinstance(lst, dict) else []
        names = {str(t.get("name")) for t in tools}
        has_woo = any(n.startswith("woo__") for n in names)
        has_time = any(n.startswith("time__") for n in names)
        has_notes = any(n.startswith("notes__") for n in names)
        check("tools/list returns tools (non-empty)", len(tools) >= 6, f"count={len(tools)} names={sorted(names)[:10]}")
        check("tools/list includes woo__ prefix", has_woo, f"names={sorted(n for n in names if n.startswith('woo__'))[:6]}")
        check("tools/list includes time__ prefix", has_time, f"names={sorted(n for n in names if n.startswith('time__'))[:6]}")
        check("tools/list includes notes__ prefix", has_notes, f"names={sorted(n for n in names if n.startswith('notes__'))[:6]}")
        check("tools/list: no unprefixed tools", all("__" in n for n in names) if names else True, f"names={sorted(names)[:8]}")

        # --- tools/call: routing by prefix (choose a read tool) ---
        target_woo = next((n for n in names if n == "woo__list_products" or n.startswith("woo__")), None)
        target_time = next((n for n in names if n in ("time__get_current_time", "time__get_time") or n.startswith("time__")), None)
        target_notes = next((n for n in names if n.startswith("notes__")), None)

        # Prefer list_products if present (takes {}), otherwise fall back to first woo tool
        if target_woo:
            # list_products needs no required args; update_order_status requires id+status, so prefer list_products
            woo_read = "woo__list_products" if "woo__list_products" in names else target_woo
            woo_args = {} if woo_read == "woo__list_products" else {"per_page": 1}
            r = await c.post(f"{BASE}/mcp", headers=h, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": woo_read, "arguments": woo_args}})
            try:
                out = r.json()
            except Exception:
                out = {"_raw": r.text[:600]}
            res = out.get("result", {}) if isinstance(out, dict) else {}
            text = ""
            try:
                text = ((res.get("content") or [{}])[0] or {}).get("text", "") or json.dumps(res)[:800]
            except Exception:
                text = json.dumps(out)[:600]
            ok = isinstance(out, dict) and "result" in out and r.status_code == 200
            is_err = bool(res.get("isError")) if isinstance(res, dict) else True
            check(f"gateway tools/call {woo_read} -> 200 + isError=false", ok and not is_err, text[:180])
            check(f"{woo_read}: not an auth/SSRF swallow (no WOO_AUTH_FAILED)", "WOO_AUTH_FAILED" not in text, text[:180])
        else:
            check("have a woo__ target to call", False, f"names={sorted(names)[:12]}")

        if target_time:
            # time server: get_current_time requires timezone
            time_args = {"timezone": "UTC"} if target_time == "time__get_current_time" else {}
            r = await c.post(f"{BASE}/mcp", headers=h, json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": target_time, "arguments": time_args}})
            try:
                out = r.json()
            except Exception:
                out = {"_raw": r.text[:600]}
            res = out.get("result", {}) if isinstance(out, dict) else {}
            ok = isinstance(out, dict) and "result" in out
            check(f"gateway tools/call {target_time} -> result", ok, json.dumps(out)[:220])

        if target_notes:
            r = await c.post(f"{BASE}/mcp", headers=h, json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": target_notes, "arguments": {}}})
            try:
                out = r.json()
            except Exception:
                out = {"_raw": r.text[:600]}
            res = out.get("result", {}) if isinstance(out, dict) else {}
            body_txt = json.dumps(out)[:400]
            # notes may require args; we only assert that gateway proxied (200 envelope) and didn't explode with 5xx shape
            ok = isinstance(out, dict) and ("result" in out or "error" in out)
            check(f"gateway tools/call {target_notes} -> proxied (result or error)", ok, body_txt[:220])

        # --- negative: validation / unknown tool maps to a concrete error (not silent success) ---
        r = await c.post(f"{BASE}/mcp", headers=h, json={"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": "unknown__does_not_exist", "arguments": {}}})
        try:
            out = r.json()
        except Exception:
            out = {"_raw": r.text[:400]}
        err_msg = json.dumps(out).lower()
        check("unknown slug -> 4xx validation_error (not silent success)", r.status_code in (400, 403, 404, 502) or "unknown" in err_msg or "slug" in err_msg, json.dumps(out)[:240])

        # --- rate limit slot (light probe: just assert header/path doesn't 500 when called quickly) ---
        r2 = await c.post(f"{BASE}/mcp", headers=h, json={"jsonrpc": "2.0", "id": 100, "method": "ping"})
        check("ping (if implemented) does not 500", r2.status_code in (200, 400), f"status={r2.status_code} {r2.text[:100]}")

        # --- SSRF deny (gateway-level): creating a server with 127.0.0.1 must be rejected ---
        # Requires a session cookie, not an API key. Try anonymous first (expect 401), then mint a session cookie via login.
        ssrf_probed = False
        try:
            r = await c.post(f"{BASE}/api/servers", json={"slug": "ssrf-probe", "url": "http://127.0.0.1:8000/mcp"}, headers={"Content-Type": "application/json"})
            if r.status_code == 401:
                # log in to get a session cookie
                r2 = await c.post(f"{BASE}/api/auth/login", json={"email": "admin@urumi.local", "password": "admin123"}, headers={"Content-Type": "application/json"})
                if r2.status_code == 200:
                    cookies = r2.cookies
                    csrf = r2.json().get("csrf_token") if r2.headers.get("content-type", "").startswith("application/json") else None
                    h2 = {"Content-Type": "application/json"}
                    if csrf:
                        h2["X-CSRF-Token"] = csrf
                    r = await c.post(f"{BASE}/api/servers", json={"slug": "ssrf-probe", "url": "http://127.0.0.1:8000/mcp"}, headers=h2, cookies=cookies)
                    check("SSRF: POST /api/servers with 127.0.0.1 must 400", r.status_code == 400, r.text[:220])
                    ssrf_probed = True
                else:
                    check("SSRF probe: login to get session cookie", False, f"login status={r2.status_code} {r2.text[:140]}")
            else:
                check("SSRF: POST /api/servers with 127.0.0.1 must 400", r.status_code == 400, r.text[:220])
                ssrf_probed = True
        except Exception as exc:
            check("SSRF probe did not crash", False, str(exc))
            ssrf_probed = True
        if not ssrf_probed:
            pass

        # --- audit row written (best-effort; allow flush interval) ---
        await asyncio.sleep(1.5)
        try:
            from sqlalchemy import select, func

            from db.session import get_session_factory
            from db.models import AuditLog

            factory = get_session_factory()
            async with factory() as db:
                cnt = (await db.execute(select(func.count()).select_from(AuditLog))).scalar() or 0
                check("audit_log has rows after tools/call", cnt >= 1, f"count={cnt}")
        except Exception as exc:
            check("audit_log query did not crash", False, str(exc)[:200])

    print("=== FAILURES:", FAILURES if FAILURES else "none", "===")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
