#!/usr/bin/env bash
# verify-prod.sh <base-domain>  - READ-ONLY prod gate, safe to run against the live
# VPS from outside. Never mutates anything (no demo-reset, no data writes, no MCP
# write calls); the only authenticated call is the read-only MCP tools/list probe.
#
# Checks:
#   1. https 200 on store.<domain> and dashboard.<domain>
#   2. certificate valid + issuer printed
#   3. http -> https redirect on both hosts
#   4. security headers present (CSP, nosniff, frame deny / frame-ancestors)
#   5. session cookie flags (Secure, HttpOnly, SameSite) on the REAL login
#      response - only when VERIFY_ADMIN_PASSWORD is set; SKIPPED otherwise
#   6. upstream services NOT routed through the public edge: probes the hostnames
#      woo-mcp/demo-time/demo-notes/mcp/gateway/postgres/mariadb via
#      curl --resolve <name>:443:<server-ip> (server IP resolved from the store
#      host). PASS on 404/421 (no route); FAIL on 2xx/3xx/401/403/5xx (upstream
#      exposed); connection failure (000) is reported as "not answered".
#   7. ports on that server IP: 80/443 open, the private/service/admin ports
#      closed or filtered (timeouts count as filtered, PASS), 22 informational.
#      Uses nc -z -w 3 with a bash /dev/tcp fallback - NO GNU timeout dependency.
#   8. MCP endpoint with an API key supplied via environment lists 13 tools.
#      SKIPPED with a clear message when MCP_KEY is unset (never prints the key).
#   9. gateway reachable through the public edge and answering JSON, NOT the
#      dashboard's HTML (the gateway's real /healthz is cluster-internal only).
#
# Env (none required):
#   MCP_KEY=<gateway API key>            enables check 8; used only in memory
#   VERIFY_ADMIN_PASSWORD=<gateway admin password>   enables check 5; never printed
#   VERIFY_ADMIN_EMAIL=<gateway admin email>         default admin@urumi.local
#   INSECURE=1                           LOCAL kind rehearsal only (self-signed cert)
#
# Exit code: 1 if and only if at least one check FAILed. SKIPPED/INFO lines never
# fail the gate.
set -eu
DOMAIN=${1:?usage: verify-prod.sh <base-domain>}
STORE="store.$DOMAIN"
DASH="dashboard.$DOMAIN"
UA="verify-prod/1.1"
FAIL=0
TMP=$(mktemp -d "${TMPDIR:-/tmp}/verify-prod.XXXXXX") || exit 1
trap 'rm -rf "$TMP"' EXIT
# INSECURE=1 for the LOCAL kind rehearsal only (self-signed kind cert). The real
# VPS run is strict (no -k) so a bad certificate FAILS the gate.
INSECURE_FLAG=""
if [ "${INSECURE:-0}" = 1 ]; then INSECURE_FLAG="-k"; fi

ok()   { printf '  PASS %s\n' "$1"; }
bad()  { printf '  FAIL %s\n' "$1"; FAIL=1; }
skip() { printf '  SKIPPED %s\n' "$1"; }
info() { printf '  INFO %s\n' "$1"; }

# resolve_ip <host>: first IPv4 A record, macOS-portable (dig -> dscacheutil ->
# nslookup). Prints nothing when resolution fails.
resolve_ip() {
  local h=$1 ip=""
  if command -v dig >/dev/null 2>&1; then
    ip=$(dig +short "$h" A 2>/dev/null | grep -E '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' | head -1)
  fi
  if [ -z "$ip" ]; then
    ip=$(dscacheutil -q host -a name "$h" 2>/dev/null | awk '/ip_address:/{print $2; exit}')
  fi
  if [ -z "$ip" ] && command -v nslookup >/dev/null 2>&1; then
    ip=$(nslookup "$h" 2>/dev/null | awk '/^Address: /{print $2; exit}')
  fi
  printf '%s' "${ip:-}"
}

# probe_tcp <ip> <port>: exit 0 = open, non-zero = closed OR filtered (timeout).
# macOS nc -z -w 3 does NOT bound a connect to a filtered (SYN-dropped) port, so
# the probe ALWAYS runs in the background with a 3s watchdog kill - that is what
# makes timeouts count as filtered. The /dev/tcp fallback is used only when nc is
# missing. No GNU 'timeout' binary anywhere.
probe_tcp() {
  local ip=$1 port=$2 cpid wpid rc
  if command -v nc >/dev/null 2>&1; then
    nc -z -w 3 "$ip" "$port" >/dev/null 2>&1 &
  else
    bash -c "exec 3<>/dev/tcp/$ip/$port" 2>/dev/null &
  fi
  cpid=$!
  ( sleep 3; kill "$cpid" 2>/dev/null ) >/dev/null 2>&1 &
  wpid=$!
  wait "$cpid" 2>/dev/null
  rc=$?
  kill "$wpid" 2>/dev/null
  wait "$wpid" 2>/dev/null || true
  return "$rc"
}

echo "== 1. https status =="
for H in "$STORE" "$DASH"; do
  CODE=$(curl $INSECURE_FLAG -s -o /dev/null -w '%{http_code}' -A "$UA" --max-time 15 "https://$H/" || echo 000)
  [ "$CODE" = 200 ] && ok "https://$H/ -> $CODE" || bad "https://$H/ -> $CODE (want 200)"
done

echo "== 2. certificate =="
CERT=$(echo | openssl s_client -connect "$DASH:443" -servername "$DASH" 2>/dev/null | openssl x509 -noout -subject -issuer -dates 2>/dev/null || true)
if [ -n "$CERT" ]; then
  ok "certificate for $DASH"
  echo "$CERT" | sed 's/^/       /'
else
  bad "no certificate served for $DASH"
fi

echo "== 3. http -> https redirect =="
for H in "$STORE" "$DASH"; do
  LOC=$(curl $INSECURE_FLAG -s -o /dev/null -w '%{http_code} %{redirect_url}' -A "$UA" --max-time 15 "http://$H/" || echo "000 ")
  case "$LOC" in
    301*https*|308*https*) ok "http://$H -> $LOC" ;;
    *) bad "http://$H -> $LOC (want 301/308 to https)" ;;
  esac
done

echo "== 4. security headers =="
HEADERS=$(curl $INSECURE_FLAG -s -D - -o /dev/null -A "$UA" --max-time 15 "https://$DASH/" || true)
for want in "content-security-policy" "x-content-type-options"; do
  printf '%s' "$HEADERS" | tr -d '\r' | grep -qi "$want" && ok "$want present" || bad "$want MISSING"
done
printf '%s' "$HEADERS" | tr -d '\r' | grep -qi "x-frame-options\|frame-ancestors" && ok "frame protection present" || bad "frame protection MISSING"

echo "== 5. session cookie flags (from the real login response) =="
# Optional: only runs when VERIFY_ADMIN_PASSWORD is set (fed via a hidden prompt,
# never committed). The password goes to curl on stdin (never argv), and neither
# the password nor the cookie VALUE is ever printed - only the flag names.
if [ -n "${VERIFY_ADMIN_PASSWORD:-}" ]; then
  EMAIL="${VERIFY_ADMIN_EMAIL:-admin@urumi.local}"
  CODE=$(printf '{"email":"%s","password":"%s"}' "$EMAIL" "$VERIFY_ADMIN_PASSWORD" | \
    curl $INSECURE_FLAG -s -D "$TMP/login-hdr.txt" -o "$TMP/login-body.txt" \
      -w '%{http_code}' -A "$UA" --max-time 15 -X POST "https://$DASH/api/auth/login" \
      -H 'Content-Type: application/json' -d @- || echo 000)
  if [ "$CODE" != 200 ]; then
    bad "login POST /api/auth/login -> $CODE (not checking cookie flags)"
  else
    SC=$(tr -d '\r' < "$TMP/login-hdr.txt" | grep -i '^set-cookie:' | head -1)
    if [ -z "$SC" ]; then
      bad "no Set-Cookie header in the login response"
    else
      FLAGS=$(printf '%s' "$SC" | cut -d';' -f2-)
      for F in Secure HttpOnly SameSite; do
        printf '%s' "$FLAGS" | grep -qi "$F" && ok "cookie flag $F present" || bad "cookie flag $F MISSING"
      done
    fi
  fi
else
  skip "login cookie check: set VERIFY_ADMIN_PASSWORD to run it (the password is never printed); e.g. read -rs pw && VERIFY_ADMIN_PASSWORD=\"\$pw\" scripts/verify-prod.sh $DOMAIN"
fi

echo "== 6. upstream services NOT routed through the public edge =="
SERVER_IP=$(resolve_ip "$STORE")
if [ -z "$SERVER_IP" ]; then
  bad "could not resolve $STORE to a server IP (probes skipped)"
else
  # Method: curl --resolve <name>:443:<server-ip> forces the connect to the PUBLIC
  # IP with the hostname as SNI, exactly as DNS would route it. -k is used here
  # ONLY for routing (a host with no ingress route gets nginx's default fake cert);
  # real certificate validity is check 2 above.
  echo "  method: curl -k --resolve <name>:443:$SERVER_IP (server IP from $STORE)"
  for NAME in woo-mcp demo-time demo-notes mcp gateway postgres mariadb; do
    H="$NAME.$DOMAIN"
    CODE=$(curl -k -s -o /dev/null -w '%{http_code}' -A "$UA" --max-time 10 \
      --resolve "$H:443:$SERVER_IP" "https://$H/" || echo 000)
    case "$CODE" in
      000)      info "$H -> $CODE (not answered: no route)" ;;
      404|421)  ok "$H -> $CODE (no route through the ingress)" ;;
      2??|3??|401|403|5*) bad "$H ANSWERED $CODE (upstream exposed through the edge!)" ;;
      *)        info "$H -> $CODE (no upstream signature; treated as not routed)" ;;
    esac
  done
  # the store host itself must never proxy MCP (wordpress answers 404, not the gateway)
  CODE=$(curl -k -s -o /dev/null -w '%{http_code}' -A "$UA" --max-time 10 \
    --resolve "$STORE:443:$SERVER_IP" "https://$STORE/mcp" -X POST \
    -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"ping"}' || echo 000)
  case "$CODE" in
    404|421)  ok "store host does not proxy MCP ($CODE)" ;;
    2??|3??|401|403|5*) bad "store host proxies MCP ($CODE) - MUST NOT" ;;
    000)      info "store /mcp -> $CODE (not answered)" ;;
    *)        ok "store host does not proxy MCP ($CODE)" ;;
  esac
fi

echo "== 7. ports on the server IP =="
if [ -z "$SERVER_IP" ]; then
  bad "no server IP to probe (port checks skipped)"
else
  echo "  server IP: $SERVER_IP (nc -z -w 3; bash /dev/tcp fallback; no timeout binary)"
  for P in 80 443 8000 8080 3306 5432 6443 10250 2379 22; do
    if probe_tcp "$SERVER_IP" "$P"; then
      case $P in
        80|443) ok "port $P open (expected)" ;;
        22)     info "port 22 open (SSH; expected for the owner, informational)" ;;
        *)      bad "port $P OPEN (want closed or filtered)" ;;
      esac
    else
      case $P in
        80|443) bad "port $P closed/filtered (want open)" ;;
        22)     info "port 22 closed (informational only)" ;;
        *)      ok "port $P closed or filtered (timeout counts as filtered)" ;;
      esac
    fi
  done
fi

echo "== 8. MCP tools/list with API key (read-only) =="
if [ -z "${MCP_KEY:-}" ]; then
  skip "MCP handshake + tools/list (set MCP_KEY in the environment to run it; the key is used only in memory and never printed)"
else
  TOOLS=$(curl $INSECURE_FLAG -sS --max-time 20 -X POST "https://$DASH/mcp" \
    -H "Authorization: Bearer $MCP_KEY" -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"verify-prod","version":"1.0"}}}' || true)
  if echo "$TOOLS" | grep -q "serverInfo"; then ok "MCP initialize handshake OK"; else bad "MCP initialize failed: $(echo "$TOOLS" | head -c 120)"; fi
  SID=$(echo "$TOOLS" | grep -o '"mcp-session-id": *"[^"]*"' | head -1 | cut -d'"' -f4)
  TOOLS_RESP=$(curl $INSECURE_FLAG -s --max-time 20 -X POST "https://$DASH/mcp" \
    -H "Authorization: Bearer $MCP_KEY" -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    ${SID:+-H "mcp-session-id: $SID"} \
    -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' || true)
  TOOL_COUNT=$(echo "$TOOLS_RESP" | grep -o '"name":"[^"]*"' | wc -l | tr -d ' ')
  if [ "$TOOL_COUNT" -ge 13 ]; then ok "MCP tools/list returned $TOOL_COUNT tools (>= 13)"; else bad "MCP tools/list returned $TOOL_COUNT tools (want >= 13): $(echo "$TOOLS_RESP" | head -c 160)"; fi
fi

echo "== 9. gateway reachability through the public edge (JSON, not HTML) =="
# The gateway's real health path in code is /healthz (src/gateway/routes/health.py:14,
# returns {"status":"ok","service":...,"version":...}) but it is deliberately NOT
# routed through the public ingress: the dashboard host exposes only /api and /mcp
# to the gateway, so a public /healthz probe would hit the dashboard's catch-all
# HTML (200) - the old false PASS. The public-host liveness proof is a real gateway
# API route instead: GET /api/me (src/gateway/routes/users.py:110) without a session
# answers 401 with a JSON body. We assert the body is JSON and NOT the dashboard's
# HTML, and print only the status + a short field.
API_CODE=$(curl $INSECURE_FLAG -s -o "$TMP/api-me.txt" -w '%{http_code}' -A "$UA" --max-time 10 "https://$DASH/api/me" || echo 000)
case "$API_CODE" in
  000) bad "gateway API unreachable through the public edge ($API_CODE)" ;;
  401|403)
    if grep -qi '<html' "$TMP/api-me.txt" 2>/dev/null; then
      bad "/api/me -> $API_CODE but the body is HTML (dashboard catch-all? gateway route not wired?)"
    else
      DETAIL=$(tr -d '\r\n' < "$TMP/api-me.txt" 2>/dev/null | grep -o '"detail":"[^"]*"' | head -1)
      ok "gateway API answering behind auth: /api/me -> $API_CODE, JSON body (${DETAIL:-no detail field})"
    fi
    ;;
  *) bad "/api/me -> $API_CODE (want 401/403 JSON behind auth)" ;;
esac

if [ "$FAIL" = 0 ]; then
  echo "VERIFY-PROD: ALL CHECKS PASSED for $DOMAIN"
else
  echo "VERIFY-PROD: FAILURES (see above)"
  exit 1
fi
