#!/usr/bin/env bash
# Phase 5 isolation proof (HOST, local kind only): cross-store NetworkPolicy.
#
# From store A's woo-mcp pod (python):
#   1. store A's own WordPress:80        -> connect-OK   (the MCP bridge depends on it)
#   2. store B's WordPress:80            -> BLOCKED      (egress: own namespace only)
#   3. store B's MariaDB:3306            -> BLOCKED
# From store A's WordPress pod (php):
#   4. store A's own MariaDB:3306        -> connect-OK
#   5. store B's MariaDB:3306            -> BLOCKED
#
# Usage: bash scripts/lib/phase5_isolation.sh <slugA> <slugB>
set -euo pipefail

CONTEXT="$(kubectl config current-context 2>/dev/null || true)"
if [[ "${CONTEXT}" != kind-* ]]; then
  echo "REFUSING: kubectl context is '${CONTEXT}' (must start with kind-)." >&2
  exit 2
fi

A="${1:?store A slug required}"
B="${2:?store B slug required}"
NSA="store-${A}"
NSB="store-${B}"

WOO_POD="$(kubectl get pods -n "${NSA}" -l app=woo-mcp -o jsonpath='{.items[0].metadata.name}')"
WP_POD="$(kubectl get pods -n "${NSA}" -l app=wordpress -o jsonpath='{.items[0].metadata.name}')"
RC=0

echo "== isolation proof: A=${NSA} B=${NSB} =="

WOO_OUT="$(kubectl exec -n "${NSA}" "${WOO_POD}" -c woo-mcp -- python3 -c "
import socket

def probe(host, port):
    s = socket.socket(); s.settimeout(4)
    try:
        s.connect((host, port)); s.close()
        return 'connect-OK'
    except Exception as e:
        return 'BLOCKED ' + type(e).__name__

print('own-wp', probe('${A}-wordpress.${NSA}.svc', 80))
print('other-wp', probe('${B}-wordpress.${NSB}.svc', 80))
print('other-mariadb', probe('${B}-mariadb.${NSB}.svc', 3306))
")"
echo "${WOO_OUT}"

WP_OUT="$(kubectl exec -n "${NSA}" "${WP_POD}" -c wordpress -- php -r '
function probe($h, $p) {
    $s = @fsockopen($h, $p, $errno, $errstr, 4);
    if ($s) { fclose($s); return "connect-OK"; }
    return "BLOCKED " . $errno;
}
echo "own-mariadb " . probe("'"${A}"'-mariadb.'"${NSA}"'.svc", 3306) . PHP_EOL;
echo "other-mariadb " . probe("'"${B}"'-mariadb.'"${NSB}"'.svc", 3306) . PHP_EOL;
' 2>/dev/null || echo "PHP-PROBE-SKIPPED")"
echo "${WP_OUT}"

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; RC=1; }

grep -q "own-wp connect-OK" <<< "${WOO_OUT}" && pass "A.woo-mcp -> A.wordpress" || fail "A.woo-mcp -> A.wordpress must connect"
grep -qE "other-wp BLOCKED" <<< "${WOO_OUT}" && pass "A.woo-mcp -X B.wordpress" || fail "A.woo-mcp -> B.wordpress must be blocked"
grep -qE "other-mariadb BLOCKED" <<< "${WOO_OUT}" && pass "A.woo-mcp -X B.mariadb" || fail "A.woo-mcp -> B.mariadb must be blocked"
grep -qE "own-mariadb connect-OK" <<< "${WP_OUT}" && pass "A.wordpress -> A.mariadb" || fail "A.wordpress -> A.mariadb must connect"
grep -qE "other-mariadb BLOCKED" <<< "${WP_OUT}" && pass "A.wordpress -X B.mariadb" || fail "A.wordpress -> B.mariadb must be blocked"

[[ ${RC} -eq 0 ]] && echo "ISOLATION: ALL CHECKS PASSED" || echo "ISOLATION: FAILURES PRESENT"
exit ${RC}
