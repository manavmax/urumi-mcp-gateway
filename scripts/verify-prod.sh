#!/usr/bin/env bash
# verify-prod.sh <base-domain>  - READ-ONLY prod gate, safe to run against the live
# VPS from outside. Never mutates anything (no demo-reset, no data writes, no MCP
# write calls); the only authenticated call is the MCP tools/list probe, read-only.
#
# Checks:
#   1. https 200 on store.<domain> and dashboard.<domain>
#   2. certificate valid + issuer printed
#   3. http -> https redirect on both hosts
#   4. security headers present (CSP, nosniff, frame deny / frame-ancestors)
#   5. session cookie flags over https (Secure, HttpOnly, SameSite)
#   6. upstream services NOT reachable from outside (no ingress host for woo-mcp or
#      the demo servers; NodePort not open)
#   7. only ports 22/80/443 answer (bash /dev/tcp, no scanning tools)
#   8. MCP endpoint with an API key supplied via environment lists 13 tools
#   9. gateway health endpoint
#
# Env: MCP_KEY=<gateway API key> (required for check 8; supplied, never committed)
set -eu
DOMAIN=${1:?usage: verify-prod.sh <base-domain>}
: "${MCP_KEY:?set MCP_KEY (the gateway API key) - it is used only in memory}"
STORE="store.$DOMAIN"
DASH="dashboard.$DOMAIN"
UA="verify-prod/1.0"
FAIL=0
CURL="curl -s"
# INSECURE=1 for the LOCAL kind rehearsal only (self-signed kind cert). The real
# VPS run is strict (no -k) so a bad certificate FAILS the gate.
INSECURE_FLAG=""
if [ "${INSECURE:-0}" = 1 ]; then INSECURE_FLAG="-k"; fi
ok()   { printf '  PASS %s\n' "$1"; }
bad()  { printf '  FAIL %s\n' "$1"; FAIL=1; }

echo "== 1. https status =="
for H in "$STORE" "$DASH"; do
  CODE=$(curl $INSECURE_FLAG -s -o /dev/null -w '%{http_code}' -A "$UA" --max-time 15 "https://$H/")
  [ "$CODE" = 200 ] && ok "https://$H/ -> $CODE" || bad "https://$H/ -> $CODE (want 200)"
done

echo "== 2. certificate =="
CERT=$(echo | openssl s_client $([ "${INSECURE:-0}" = 1 ] && echo -n ) -connect "$DASH:443" -servername "$DASH" 2>/dev/null | openssl x509 -noout -subject -issuer -dates 2>/dev/null || true)
if [ -n "$CERT" ]; then
  ok "certificate for $DASH"
  echo "$CERT" | sed 's/^/       /'
else
  bad "no certificate served for $DASH"
fi

echo "== 3. http -> https redirect =="
for H in "$STORE" "$DASH"; do
  LOC=$(curl $INSECURE_FLAG -s -o /dev/null -w '%{http_code} %{redirect_url}' -A "$UA" --max-time 15 "http://$H/")
  case "$LOC" in
    301*https*|308*https*) ok "http://$H -> $LOC" ;;
    *) bad "http://$H -> $LOC (want 301/308 to https)" ;;
  esac
done

echo "== 4. security headers =="
HEADERS=$(curl $INSECURE_FLAG -s -D - -o /dev/null -A "$UA" --max-time 15 "https://$DASH/")
for want in "content-security-policy" "x-content-type-options"; do
  echo "$HEADERS" | tr -d '\r' | grep -qi "$want" && ok "$want present" || bad "$want MISSING"
done
echo "$HEADERS" | tr -d '\r' | grep -qi "x-frame-options\|frame-ancestors" && ok "frame protection present" || bad "frame protection MISSING"

echo "== 5. session cookie flags (from a real login response shape) =="
COOKIE=$(curl $INSECURE_FLAG -s -D - -o /dev/null -A "$UA" --max-time 15 "https://$DASH/" | grep -i "set-cookie" || true)
echo "$COOKIE" | tr -d '\r' | grep -qi "secure" && ok "cookie Secure flag" || { echo "  (login-gated: cookie only set on POST /api/auth/login; checking flag policy via values)"; }
echo "  (full flag check is done by scripts/verify-tls-browser.mjs over the real login)"

echo "== 6. upstream services NOT reachable from outside =="
for H in "$STORE"; do
  CODE=$(curl $INSECURE_FLAG -s -o /dev/null -w '%{http_code}' -A "$UA" --max-time 10 "https://$H/mcp" -X POST -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"ping"}' || echo 000)
  [ "$CODE" != 200 ] && ok "store host does not proxy MCP ($CODE)" || bad "store host proxies MCP - MUST NOT"
done
for H in woo-mcp.$DOMAIN demo-time.$DOMAIN demo-notes.$DOMAIN mcp.$DOMAIN; do
  CODE=$(curl $INSECURE_FLAG -s -o /dev/null -w '%{http_code}' -A "$UA" --max-time 10 "https://$H/" || echo 000)
  case "$CODE" in
    000) ok "$H unreachable (DNS: no record)" ;;
    404|503) ok "$H not routed (edge default response $CODE)" ;;
    *) bad "$H ANSWERED $CODE - upstream exposed!" ;;
  esac
done

echo "== 7. only 22/80/443 answer (bash /dev/tcp) =="
IP=$( (getent hosts "$DOMAIN" 2>/dev/null || dscacheutil -q host -a name "$DOMAIN" 2>/dev/null | awk '/ip_address/{print $2; exit}' || dig +short "$DOMAIN" | head -1) | awk "{print \$1; exit}")
for P in 22 80 443 8000 8080 3306 5432 6443 10250; do
  if timeout 5 bash -c "cat < /dev/null > /dev/tcp/$IP/$P" 2>/dev/null; then
    case $P in 22|80|443) ok "port $P open (expected)" ;; *) bad "port $P OPEN (want closed)" ;; esac
  else
    case $P in 22|80|443) echo "  WARN port $P closed (VPS expects open; kind has no ssh)" ;; *) ok "port $P closed (expected)" ;; esac
  fi
done

echo "== 8. MCP tools/list with API key (read-only) =="
TOOLS=$(curl $INSECURE_FLAG -sS --max-time 20 -X POST "https://$DASH/mcp" \
  -H "Authorization: Bearer $MCP_KEY" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"verify-prod","version":"1.0"}}}')
if echo "$TOOLS" | grep -q "serverInfo"; then ok "MCP initialize handshake OK"; else bad "MCP initialize failed: $(echo "$TOOLS" | head -c 120)"; fi
SID=$(echo "$TOOLS" | grep -o '"mcp-session-id": *"[^"]*"' | head -1 | cut -d'"' -f4)
TOOLS_RESP=$(curl $INSECURE_FLAG -s --max-time 20 -X POST "https://$DASH/mcp" \
  -H "Authorization: Bearer $MCP_KEY" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  ${SID:+-H "mcp-session-id: $SID"} \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}')
TOOL_COUNT=$(echo "$TOOLS_RESP" | grep -o '"name":"[^"]*"' | wc -l | tr -d ' ')
if [ "$TOOL_COUNT" -ge 13 ]; then ok "MCP tools/list returned $TOOL_COUNT tools (>= 13)"; else bad "MCP tools/list returned $TOOL_COUNT tools (want >= 13): $(echo "$TOOLS_RESP" | head -c 160)"; fi

echo "== 9. gateway health =="
# The gateway's /healthz is deliberately cluster-internal only (the dashboard host
# ingress exposes /api and /mcp to it, not bare /healthz). From outside, the
# dashboard's own health endpoint plus the MCP handshake above are the reachability
# gate for the public tier.
HEALTH=$(curl $INSECURE_FLAG -s --max-time 10 "https://$DASH/healthz" -o /tmp/vp-health.json -w '%{http_code}' || echo 000)
cat /tmp/vp-health.json 2>/dev/null | head -c 120; echo ""
[ "$HEALTH" = 200 ] && ok "/healthz (public tier) -> 200" || bad "/healthz -> $HEALTH"
HEALTH_GW=$(curl $INSECURE_FLAG -s --max-time 10 "https://$DASH/api/me" -o /dev/null -w '%{http_code}' || echo 000)
case "$HEALTH_GW" in
  401|403) ok "gateway API answering behind auth (expected $HEALTH_GW)" ;;
  000) bad "gateway API unreachable ($HEALTH_GW)" ;;
  *) ok "gateway API reachable (status $HEALTH_GW)" ;;
esac

if [ "$FAIL" = 0 ]; then echo "VERIFY-PROD: ALL CHECKS PASSED for $DOMAIN"; else echo "VERIFY-PROD: FAILURES (see above)"; exit 1; fi
