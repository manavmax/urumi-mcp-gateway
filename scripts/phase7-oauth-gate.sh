#!/usr/bin/env bash
# Phase 7 (ADR-063) LIVE gate: the full OAuth flow against the deployed kind
# gateway through the ingress, exactly as an MCP client would drive it:
#   1. unauthenticated /mcp -> 401 + WWW-Authenticate (RFC 9728 pointer)
#   2. fetch protected-resource + authorization-server metadata
#   3. dynamic client registration (RFC 7591)
#   4. authorize: dashboard login (session), consent approve -> code (PKCE S256)
#   5. token exchange -> access + refresh
#   6. /mcp tools/list + tools/call with the access token (mapped to the user)
#   7. refresh -> new tokens; old access still valid (independent grant)
#   8. revoke the refresh family -> everything dead
# Context: kind-urumi ONLY.
set -euo pipefail
CONTEXT="$(kubectl config current-context)"
if [[ "${CONTEXT}" != kind-* ]]; then echo "REFUSING: context ${CONTEXT}" >&2; exit 2; fi

BASE="http://dashboard.127.0.0.1.nip.io"

# read the password WITHOUT printing it (the make target labels its output;
# take the value after "admin pass: " and export privately)
ADMIN_PASSWORD="$(make -s gateway-admin-password | sed -n 's/^admin pass: *//p' | head -1)"
test -n "${ADMIN_PASSWORD}" || { echo "could not read admin password" >&2; exit 2; }
export GATEWAY_ADMIN_PASSWORD="${ADMIN_PASSWORD}"
.venv/bin/python - "${BASE}" << 'PYEOF'
import asyncio, base64, hashlib, json, os, sys
from urllib.parse import urlparse, parse_qs

import httpx

BASE = sys.argv[1]
ADMIN_EMAIL = "admin@urumi.local"
ADMIN_PASSWORD = os.environ["GATEWAY_ADMIN_PASSWORD"]
REDIRECT = "http://127.0.0.1:9911/callback"

results: list[tuple[bool, str]] = []
def check(ok: bool, label: str, extra: str = ""):
    results.append((ok, f"{'PASS' if ok else 'FAIL'}  {label} {extra}"))

async def main():
    # 1. unauthenticated /mcp
    r = httpx.post(f"{BASE}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=15)
    check(r.status_code == 401, "unauthenticated /mcp is 401")
    wa = r.headers.get("www-authenticate", "")
    check("oauth-protected-resource" in wa, "WWW-Authenticate points at the RFC 9728 metadata", f"[{wa[:80]}]")

    # 2. metadata
    r = httpx.get(f"{BASE}/.well-known/oauth-protected-resource", timeout=15)
    check(r.status_code == 200, "protected-resource metadata served")
    meta = r.json()
    r = httpx.get(f"{BASE}/.well-known/oauth-authorization-server", timeout=15)
    check(r.status_code == 200, "authorization-server metadata served")
    asmeta = r.json()
    check("S256" in asmeta.get("code_challenge_methods_supported", []) and "plain" not in asmeta.get("code_challenge_methods_supported", []),
          "PKCE S256 only")

    # 3. dynamic client registration
    r = httpx.post(f"{BASE}/oauth/register", json={"redirect_uris": [REDIRECT], "client_name": "Phase7 gate client"}, timeout=15)
    check(r.status_code == 201, "dynamic client registration (RFC 7591)")
    client_id = r.json()["client_id"]

    # 4. authorize: dashboard login (browser part), consent approve
    async with httpx.AsyncClient(timeout=20) as browser:
        r = await browser.post(f"{BASE}/api/auth/login",
                               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        check(r.status_code == 200, "dashboard login (browser session reuse)")
        csrf = r.json()["csrf_token"]
        verifier = base64.urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        resource = meta["resource"]
        params = {
            "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
            "scope": "mcp", "state": "live-gate", "resource": resource,
            "code_challenge": challenge, "code_challenge_method": "S256",
        }
        r = await browser.get(f"{BASE}/oauth/authorize", params=params)
        check(r.status_code == 200 and "Authorize access" in r.text, "consent page renders")
        # CSRF token for the consent POST comes from /api/me
        r = await browser.get(f"{BASE}/api/me", headers={"X-CSRF-Token": csrf})
        csrf = r.json().get("csrf_token", csrf)
        r = await browser.post(f"{BASE}/oauth/authorize",
                               data={**params, "decision": "approve"},
                               headers={"X-CSRF-Token": csrf}, follow_redirects=False)
        check(r.status_code == 302, "consent approve -> 302 with code")
        loc = r.headers["location"]
        q = parse_qs(urlparse(loc).query)
        code = q.get("code", [""])[0]
        check(bool(code) and q.get("state") == ["live-gate"], "code + state returned to the client")

    # 5. token exchange (PKCE verifier)
    r = httpx.post(f"{BASE}/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "client_id": client_id,
        "redirect_uri": REDIRECT, "code_verifier": verifier, "resource": resource,
    }, timeout=15)
    check(r.status_code == 200, "token exchange (PKCE verified)")
    tok = r.json()
    access, refresh = tok.get("access_token", ""), tok.get("refresh_token", "")

    # 6. /mcp with the access token (mapped to the admin user)
    r = httpx.post(f"{BASE}/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                   headers={"Authorization": f"Bearer {access}"}, timeout=30)
    tools = len(r.json().get("result", {}).get("tools", [])) if r.status_code == 200 else 0
    check(r.status_code == 200 and tools > 0, "tools/list via OAuth bearer token", f"[tools={tools}]")
    r = httpx.post(f"{BASE}/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                        "params": {"name": "time__get_current_time", "arguments": {}}},
                   headers={"Authorization": f"Bearer {access}"}, timeout=30)
    check(r.status_code == 200, "tools/call via OAuth bearer token (audited under the user)")

    # 7. refresh
    r = httpx.post(f"{BASE}/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": refresh,
        "client_id": client_id, "resource": resource,
    }, timeout=15)
    check(r.status_code == 200, "refresh grants new tokens (rotation)")
    tok2 = r.json()
    check(tok2.get("refresh_token") != refresh, "refresh token rotated")

    # 8. revoke the family -> the new access token dies
    r = httpx.post(f"{BASE}/oauth/revoke", data={"token": tok2["refresh_token"], "token_type_hint": "refresh_token"}, timeout=15)
    check(r.status_code == 200, "revoke accepted")
    r = httpx.post(f"{BASE}/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
                   headers={"Authorization": f"Bearer {tok2['access_token']}"}, timeout=30)
    check(r.status_code == 401, "family revocation kills the access token too")

    for ok, line in results:
        print(line)
    print("OAUTH-FULL-FLOW:", "OK" if all(ok for ok, _ in results) else "FAIL")

asyncio.run(main())
PYEOF
