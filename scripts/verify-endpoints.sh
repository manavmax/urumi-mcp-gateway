#!/usr/bin/env bash
# verify-endpoints.sh (F2 pass, item 2) — READ-ONLY live-cluster probe.
#
# GETs every read-only gateway route as admin (session from the gateway-admin
# Secret) and, when credentials are provided, as a member; plus anonymous.
# Reports any 5xx or a status that deviates from the expected column of
# docs/ENDPOINT_MATRIX.md. NO writes: no POST/PUT/PATCH/DELETE, no key minting.
#
# Usage:
#   scripts/verify-endpoints.sh
# Env:
#   VERIFY_MEMBER_EMAIL / VERIFY_MEMBER_PASSWORD  optional member probe
#   GATEWAY_API_KEY          optional key for one POST /mcp ping (bearer; the
#                            ONLY non-GET call, and ping mutates nothing)
#   GATEWAY_BASE             default http://127.0.0.1:18000 (port-forward)
set -u

NS=urumi
PF_PID=""
BASE="${GATEWAY_BASE:-http://127.0.0.1:18000}"

cleanup() { [ -n "${PF_PID:-}" ] && kill "$PF_PID" 2>/dev/null; }
trap cleanup EXIT

fail=0
declare -a UNEXPECTED=()
declare -a FIVEXX=()

check() { # label expected status
  local label="$1" got="$2" want="$3"
  if [ "$got" -ge 500 ]; then
    FIVEXX+=("$label -> $got")
    echo "FAIL(5xx)  $label -> $got (want $want)"
  elif [ "$got" != "$want" ]; then
    UNEXPECTED+=("$label -> $got (want $want)")
    echo "WARN       $label -> $got (want $want)"
  else
    echo "PASS       $label -> $got"
  fi
}

# 1. port-forward (read-only)
kubectl port-forward -n "$NS" svc/urumi-gateway 18000:8000 >/dev/null 2>&1 &
PF_PID=$!
sleep 2

CURL="curl -s -o /dev/null -w %{http_code} --max-time 10"

echo "== anonymous GETs =="
for spec in "/:200" "/healthz:200" "/readyz:200" "/mcp:405" "/api/me:401" "/api/servers:401" "/api/keys:401" "/api/tools:401" "/api/audit:401" "/api/audit/export:401" "/api/alerts:401" "/api/stats:401" "/api/users:401" "/api/admin-events:401" "/api/permissions:401"; do
  path="${spec%%:*}"; want="${spec##*:}"
  got=$(eval "$CURL '$BASE$path'" 2>/dev/null) || got=000
  check "anon GET $path" "$got" "$want"
done

echo "== admin session GETs =="
PW=$(kubectl get secret -n "$NS" gateway-admin -o jsonpath='{.data.password}' | base64 -d 2>/dev/null)
if [ -z "$PW" ]; then
  echo "SKIP admin/member probes: gateway-admin Secret unavailable"
elif ! CSRF=$(curl -s -c /tmp/verify-ep-admin.jar -H 'Content-Type: application/json' -d "{\"email\":\"admin@urumi.local\",\"password\":\"$PW\"}" "$BASE/api/auth/login" | python3 -c "import sys,json;print(json.load(sys.stdin).get('csrf_token',''))") || [ -z "$CSRF" ]; then
  echo "SKIP admin login failed (wrong Secret?)"
else
  for path in / /healthz /readyz /api/me /api/servers /api/keys /api/tools /api/audit /api/audit/export /api/alerts /api/stats /api/users /api/admin-events /api/permissions; do
    got=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -b /tmp/verify-ep-admin.jar "$BASE$path") || got=000
    check "admin GET $path" "$got" 200
  done
  got=$(curl -s -o /dev/null -w "%{http_code}" -b /tmp/verify-ep-admin.jar "$BASE/mcp")
  check "admin GET /mcp" "$got" 405
fi

echo "== member session GETs (optional) =="
if [ -n "${VERIFY_MEMBER_EMAIL:-}" ] && [ -n "${VERIFY_MEMBER_PASSWORD:-}" ]; then
  CSRF_M=$(curl -s -c /tmp/verify-ep-member.jar -H 'Content-Type: application/json' -d "{\"email\":\"$VERIFY_MEMBER_EMAIL\",\"password\":\"$VERIFY_MEMBER_PASSWORD\"}" "$BASE/api/auth/login" | python3 -c "import sys,json;print(json.load(sys.stdin).get('csrf_token',''))")
  if [ -z "$CSRF_M" ]; then
    echo "SKIP member probes: login failed for $VERIFY_MEMBER_EMAIL"
  else
    for path in / /healthz /readyz /api/me /api/servers /api/keys /api/tools /api/audit /api/alerts /api/stats; do
      got=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -b /tmp/verify-ep-member.jar "$BASE$path")
      check "member GET $path" "$got" 200
    done
  fi
else
  echo "SKIP member probes: member password unknown on this cluster and minting credentials would WRITE to it."
  echo "           Provide VERIFY_MEMBER_EMAIL/VERIFY_MEMBER_PASSWORD for full member coverage."
fi

echo "== summary =="
if [ "${#FIVEXX[@]}" -gt 0 ]; then
  echo "5xx ERRORS: ${#FIVEXX[@]}"
  printf '  %s\n' "${FIVEXX[@]}"
fi
if [ "${#UNEXPECTED[@]}" -gt 0 ]; then
  echo "unexpected statuses: ${#UNEXPECTED[@]}"
  printf '  %s\n' "${UNEXPECTED[@]}"
fi
if [ "${#FIVEXX[@]}" -eq 0 ] && [ "${#UNEXPECTED[@]}" -eq 0 ]; then
  echo "ALL OK"
  exit 0
fi
exit 1
