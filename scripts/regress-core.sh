#!/usr/bin/env bash
# Core Definition-of-Done regression gate (bonus-all run).
#
# Automates the core demo path on the LOCAL KIND CLUSTER ONLY, with two users
# (admin + a throwaway member):
#   1. a real storefront order (WooCommerce Store API, COD) is visible through
#      the gateway (woo__list_orders via MCP)
#   2. tools/list counts for admin and member (default allow-all)
#   3. the orders question via MCP
#   4. a revoked key is rejected on the next call
#   5. a disabled upstream hides its tools in the external MCP tools/list AND in
#      the chat agent's tool load (the same code path chat_loop uses)
#   6. killing an upstream pod: the other servers keep working, the dashboard
#      leaves "Connected", and the tool recovers when the pod returns
#   7. audit rows carry the right user attribution
#
# Guards: refuses to run unless `kubectl config current-context` starts with
# "kind-" (the VPS must NEVER be touched by this script). Never prints a
# credential: passwords come from pod env, keys stay inside the pods.
#
# Usage: bash scripts/regress-core.sh

set -euo pipefail

NAMESPACE="${NAMESPACE:-urumi}"

# ---- HARD GUARD: local kind cluster only ------------------------------------
CONTEXT="$(kubectl config current-context 2>/dev/null || true)"
if [[ "${CONTEXT}" != kind-* ]]; then
  echo "REFUSING: kubectl context is '${CONTEXT}' (must start with kind-). This script must never touch the VPS." >&2
  exit 2
fi
echo "== regress-core: context ${CONTEXT}, namespace ${NAMESPACE} =="

GW_POD="$(kubectl get pods -n "${NAMESPACE}" -l app=gateway -o jsonpath='{.items[0].metadata.name}')"
WOO_POD="$(kubectl get pods -n "${NAMESPACE}" -l app=woo-mcp -o jsonpath='{.items[0].metadata.name}')"
TIME_POD="$(kubectl get pods -n "${NAMESPACE}" -l app=demo-time -o jsonpath='{.items[0].metadata.name}')"
echo "== pods: gateway=${GW_POD} woo-mcp=${WOO_POD} demo-time=${TIME_POD} =="

kubectl wait -n "${NAMESPACE}" --for=condition=ready pod "${GW_POD}" "${WOO_POD}" "${TIME_POD}" --timeout=120s >/dev/null

RC=0

# ---- 1. place a real storefront order (Store API, COD) from the woo-mcp pod --
echo "== step 1: storefront order via Store API =="
if ! ORDER_OUT="$(kubectl exec -n "${NAMESPACE}" "${WOO_POD}" -c woo-mcp -i -- python3 - < scripts/lib/regress_store_order.py place)"; then
  echo "REGRESS-CORE: FAIL (storefront order)"; exit 1
fi
echo "${ORDER_OUT}"
ORDER_ID="$(printf '%s\n' "${ORDER_OUT}" | sed -n 's/^ORDER_ID=//p')"
if [[ -z "${ORDER_ID}" ]]; then
  echo "REGRESS-CORE: FAIL (no ORDER_ID parsed)"; exit 1
fi

# ---- 2. gateway checks: two users, tools/list counts, orders question, ------
echo "== step 2: gateway phase1 (order_id=${ORDER_ID}) =="
if ! kubectl exec -n "${NAMESPACE}" "${GW_POD}" -c gateway -i -- python3 - < scripts/lib/regress_gw.py phase1 "${ORDER_ID}"; then
  echo "REGRESS-CORE: FAIL (gateway phase1)"; RC=1
fi

if [[ ${RC} -eq 0 ]]; then
  # ---- 3. kill the demo-time pod while the gateway polls --------------------
  # START THE POLLER FIRST (background), let it warm up, THEN kill: deleting
  # first races a fast-restarting pod (the tiny local image returns in ~2s and
  # the whole dark window can elapse before the poller's first call - observed
  # flaky in phases 5-8).
  echo "== step 3: killing demo-time pod ${TIME_POD}; others must keep working =="
  kubectl exec -n "${NAMESPACE}" "${GW_POD}" -c gateway -i -- python3 - < scripts/lib/regress_gw.py during_kill &
  KILL_POLLER=$!
  sleep 3
  kubectl delete pod -n "${NAMESPACE}" "${TIME_POD}" --wait=false >/dev/null
  if ! wait "${KILL_POLLER}"; then
    echo "REGRESS-CORE: FAIL (kill-pod window)"; RC=1
  fi
  NEW_TIME_POD="$(kubectl get pods -n "${NAMESPACE}" -l app=demo-time -o jsonpath='{.items[0].metadata.name}')"
  kubectl wait -n "${NAMESPACE}" --for=condition=ready pod "${NEW_TIME_POD}" --timeout=120s >/dev/null || true
fi

# ---- 4. cleanup: throwaway user, regress keys, probe order ------------------
echo "== step 4: cleanup =="
if ! kubectl exec -n "${NAMESPACE}" "${GW_POD}" -c gateway -i -- python3 - < scripts/lib/regress_gw.py cleanup; then
  echo "REGRESS-CORE: FAIL (cleanup)"; RC=1
fi
if ! kubectl exec -n "${NAMESPACE}" "${WOO_POD}" -c woo-mcp -i -- python3 - < scripts/lib/regress_store_order.py cleanup "${ORDER_ID}"; then
  echo "REGRESS-CORE: FAIL (probe order cleanup)"; RC=1
fi

if [[ ${RC} -eq 0 ]]; then
  echo "REGRESS-CORE: ALL CHECKS PASSED"
else
  echo "REGRESS-CORE: FAILURES PRESENT (see the FAIL lines above)"
fi
exit "${RC}"
