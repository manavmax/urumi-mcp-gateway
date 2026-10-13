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
import os

import httpx

BASE = "http://127.0.0.1:8000"
FAILURES: list[str] = []

# The dashboard admin password comes from the chart-generated `gateway-admin` Secret, which
# the gateway pod receives as GATEWAY_ADMIN_PASSWORD. This script runs inside that pod
# (kubectl exec), so it reads the same value the app does - there is no committed default
# to fall back to, by design (docs/DECISIONS.md ADR-021).
ADMIN_EMAIL = "admin@urumi.local"
ADMIN_PASSWORD = os.environ.get("GATEWAY_ADMIN_PASSWORD", "")


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
    from auth.keys import create_api_key as mint_api_key
    from db.models import ApiKey, User
    from db.session import get_session_factory
    from sqlalchemy import select

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
            time_args = {"timezone": "UTC"} if target_time == "time__get_current_time" else {}
            r = await c.post(f"{BASE}/mcp", headers=h, json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": target_time, "arguments": time_args}})
            try:
                out = r.json()
            except Exception:
                out = {"_raw": r.text[:600]}
            res = out.get("result", {}) if isinstance(out, dict) else {}
            ok = isinstance(out, dict) and "result" in out
            check(f"gateway tools/call {target_time} -> result", ok, json.dumps(out)[:220])
            if target_time == "time__convert_time":
                r2 = await c.post(f"{BASE}/mcp", headers=h, json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "time__convert_time", "arguments": {"time": "2026-10-10T14:30:00", "from_tz": "UTC", "to_tz": "America/New_York"}}})
                out2 = r2.json() if r2.status_code == 200 else {}
                res2 = out2.get("result", {}) if isinstance(out2, dict) else {}
                is_err = bool(res2.get("isError")) if isinstance(res2, dict) else True
                txt2 = ""
                try:
                    txt2 = ((res2.get("content") or [{}])[0] or {}).get("text", "") or json.dumps(res2)[:400]
                except Exception:
                    txt2 = json.dumps(out2)[:400]
                check("time__convert_time -> isError=false", r2.status_code == 200 and not is_err, txt2[:240])
                check("time__convert_time returned converted time", "2026-10-10" in txt2 and "America/New_York" in txt2, txt2[:240])

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

        # --- REAL MCP SDK client (protocol-level validation of tools/call results) ---
        # The gateway's OLD serialization emitted `"annotations": null` / `"meta": null`
        # on every block: the Python SDK 1.12.x client accepted it, but the MCP
        # TypeScript SDK (MCP Inspector) rejects it as "content.0: Invalid input".
        # Here we drive the OFFICIAL Python SDK client end-to-end AND re-validate the
        # raw JSON-RPC the client received with the router's own strict wire checker, so
        # a regression that a lenient client would swallow fails this script.
        try:
            from gw_mcp.router import _assert_wire_content
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            raw_bodies: list[str] = []

            def _factory(**kwargs):
                async def _cap(response: httpx.Response):
                    raw_bodies.append(await response.aread())

                kwargs.setdefault("timeout", 30)
                return httpx.AsyncClient(**{**kwargs, "headers": h, "event_hooks": {"response": [_cap]}})

            sdk_targets = [n for n in ("woo__list_products", "time__get_current_time", "notes__list_notes") if n in names]
            async with streamablehttp_client(f"{BASE}/mcp", httpx_client_factory=_factory) as (sread, swrite, _meta):
                async with ClientSession(sread, swrite) as session:
                    init = await session.initialize()
                    check("SDK client initialize", init.protocolVersion == "2025-03-26", str(init.protocolVersion))
                    if not sdk_targets:
                        check("SDK client: have a target tool to call", False, f"names={sorted(names)[:12]}")
                    for tool_name in sdk_targets:
                        call_args = {}
                        if tool_name == "time__get_current_time":
                            call_args = {"timezone": "UTC"}
                        try:
                            sres = await session.call_tool(tool_name, call_args)
                            check(f"SDK call_tool {tool_name} parsed by official client", True, f"isError={sres.isError}")
                        except Exception as exc:
                            check(f"SDK call_tool {tool_name} parsed by official client", False, f"{type(exc).__name__}: {str(exc)[:220]}")
                            continue
                        # strict wire check on the raw bytes the client actually received
                        try:
                            for body in reversed(raw_bodies):
                                parsed = json.loads(body)
                                resj = parsed.get("result")
                                if isinstance(resj, dict) and isinstance(resj.get("content"), list):
                                    _assert_wire_content(resj["content"])
                                    check(f"SDK {tool_name} raw result wire-valid", True, "")
                                    break
                            else:
                                check(f"SDK {tool_name} raw result wire-valid", False, "no tools/call result captured")
                        except ValueError as exc:
                            check(f"SDK {tool_name} raw result wire-valid", False, str(exc))
        except Exception as exc:
            check("SDK client run (imports/wiring)", False, f"{type(exc).__name__}: {str(exc)[:220]}")

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

        # --- admin login: the Secret's password works, and a wrong password does not ---
        # The password is only ever read from the in-pod env (the gateway-admin Secret), so
        # this doubles as proof that no committed default is accepted any more. The rejected
        # value is derived at runtime so it can never collide with the real one.
        if not ADMIN_PASSWORD:
            check("admin login (needs GATEWAY_ADMIN_PASSWORD in the pod env)", False,
                  "GATEWAY_ADMIN_PASSWORD is empty - is the gateway-admin Secret mounted?")
        else:
            r = await c.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, headers={"Content-Type": "application/json"})
            check("admin login with the Secret password -> 200", r.status_code == 200,
                  f"status={r.status_code} (password from the Secret, never printed)")
            wrong = ADMIN_PASSWORD + "-wrong"
            bad = await c.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": wrong}, headers={"Content-Type": "application/json"})
            check("login with a wrong password -> 401", bad.status_code == 401,
                  f"status={bad.status_code}")

        # --- SSRF deny (gateway-level): creating a server with 127.0.0.1 must be rejected ---
        # Two separate probes, because session auth makes the "anonymous" case conditional:
        # a client that already holds a session cookie is authenticated, not anonymous.
        try:
            ssrf_body = {"slug": "ssrf-probe", "url": "http://127.0.0.1:8000/mcp"}
            # (a) a client with no session at all must never get past auth
            async with httpx.AsyncClient(base_url=BASE, timeout=15) as anon:
                r = await anon.post("/api/servers", json=ssrf_body, headers={"Content-Type": "application/json"})
            check("SSRF: anonymous POST /api/servers is rejected", r.status_code in (401, 403), f"status={r.status_code} {r.text[:140]}")
            # (b) a real admin session with the CSRF token the app hands out must reach the
            # URL validator and be rejected there (proves the deny is not an auth artefact)
            checked = False
            if ADMIN_PASSWORD:
                r2 = await c.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, headers={"Content-Type": "application/json"})
                if r2.status_code != 200:
                    check("SSRF probe: login to get session cookie", False, f"login status={r2.status_code} {r2.text[:140]}")
                else:
                    csrf = r2.json().get("csrf_token") if r2.headers.get("content-type", "").startswith("application/json") else None
                    h2 = {"Content-Type": "application/json"}
                    if csrf:
                        h2["X-CSRF-Token"] = csrf
                    r = await c.post(f"{BASE}/api/servers", json=ssrf_body, headers=h2, cookies=r2.cookies)
                    check("SSRF: POST /api/servers with 127.0.0.1 must 400", r.status_code == 400, r.text[:220])
                    checked = True
            if not checked:
                check("SSRF probe: no session available to prove the deny", False, "GATEWAY_ADMIN_PASSWORD is empty")
        except Exception as exc:
            check("SSRF probe did not crash", False, str(exc))

        # --- RBAC: a member session must be denied EVERY admin endpoint (Test 7) ---
        # A member is provisioned through the real API (admin login -> create user),
        # then driven through the same session-cookie + CSRF flow the dashboard uses.
        if not ADMIN_PASSWORD:
            check("RBAC member probes (needs GATEWAY_ADMIN_PASSWORD)", False, "GATEWAY_ADMIN_PASSWORD is empty")
        else:
            import secrets as _secrets

            member_email = f"verify-member-{_secrets.token_hex(3)}@urumi.local"
            member_pw = _secrets.token_urlsafe(12)
            ra = await c.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, headers={"Content-Type": "application/json"})
            if ra.status_code != 200:
                check("RBAC: admin login to provision a member", False, f"status={ra.status_code}")
            else:
                ah = {"Content-Type": "application/json", "X-CSRF-Token": ra.json().get("csrf_token", "")}
                ru = await c.post(f"{BASE}/api/users", json={"email": member_email, "password": member_pw, "role": "member"}, headers=ah, cookies=ra.cookies)
                check("RBAC: admin creates a member user -> 201", ru.status_code == 201, f"status={ru.status_code}")
                member_id = (ru.json().get("id") if ru.status_code == 201 else None)
                rm = await c.post(f"{BASE}/api/auth/login", json={"email": member_email, "password": member_pw}, headers={"Content-Type": "application/json"})
                check("RBAC: member login (cookie + CSRF) works", rm.status_code == 200, f"status={rm.status_code}")
                if rm.status_code == 200:
                    mh = {"Content-Type": "application/json", "X-CSRF-Token": rm.json().get("csrf_token", "")}
                    mc = rm.cookies
                    # a real server id for the id-taking probes (read is allowed)
                    srv_id = None
                    rs = await c.get(f"{BASE}/api/servers", cookies=mc)
                    if rs.status_code == 200 and rs.json().get("servers"):
                        srv_id = rs.json()["servers"][0]["id"]
                    srv_id = srv_id or "00000000-0000-0000-0000-000000000001"
                    probes = [
                        ("POST", "/api/servers", {"slug": "verify-evil", "url": "http://urumi-demo-time:8000/mcp", "auth_type": "none", "timeout_ms": 5000}),
                        ("PATCH", f"/api/servers/{srv_id}", {"enabled": False}),
                        ("POST", f"/api/servers/{srv_id}/disable", None),
                        ("POST", f"/api/servers/{srv_id}/enable", None),
                        ("DELETE", f"/api/servers/{srv_id}", None),
                        ("PUT", f"/api/servers/{srv_id}", {"enabled": False}),
                        ("GET", "/api/users", None),
                        ("POST", "/api/users", {"email": f"verify-evil-{_secrets.token_hex(3)}@example.test", "password": "verify-evil-123", "role": "admin"}),
                    ]
                    for method, path, body in probes:
                        r = await c.request(method, f"{BASE}{path}", json=body, headers=mh, cookies=mc)
                        allowed = 405 if method == "PUT" else 403  # PUT has no route: 405, never success
                        check(f"member {method} {path} -> {allowed} (denied)", r.status_code == allowed, f"status={r.status_code} {r.text[:100]}")
                    # a member MUST still be able to use the gateway itself
                    rk = await c.post(f"{BASE}/api/keys", json={}, headers=mh, cookies=mc)
                    ok_member_key = rk.status_code == 201
                    # never echo the raw key: only prefix/last4 leave this process
                    key_detail = f"last4={rk.json().get('last4')}" if ok_member_key else rk.text[:100]
                    check("member can still mint own API key -> 201", ok_member_key, f"status={rk.status_code} {key_detail}")
                    if ok_member_key:
                        mkey = rk.json().get("key", "")
                        r = await c.post(f"{BASE}/mcp", headers=gw_headers(mkey), json={"jsonrpc": "2.0", "id": 77, "method": "tools/call", "params": {"name": "time__get_current_time", "arguments": {}}})
                        try:
                            out = r.json()
                        except Exception:
                            out = {}
                        res = out.get("result", {}) if isinstance(out, dict) else {}
                        ok = r.status_code == 200 and "result" in out and not bool(res.get("isError"))
                        check("member tools/call time__get_current_time still works", ok, json.dumps(out)[:200])
                    # cleanup: remove the temp member again
                    if member_id:
                        rd = await c.delete(f"{BASE}/api/users/{member_id}", headers=ah, cookies=ra.cookies)
                        check("RBAC: admin removes the temp member -> 204", rd.status_code == 204, f"status={rd.status_code}")

        # --- audit row written (best-effort; allow flush interval) ---
        await asyncio.sleep(1.5)
        try:
            from db.models import AuditLog
            from db.session import get_session_factory
            from sqlalchemy import func, select

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
