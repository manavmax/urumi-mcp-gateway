#!/usr/bin/env bash
# demo-reset.sh -- reset the demo dataset to a clean, demo-ready state.
#
# Default is a DRY RUN: it prints what WOULD be deleted (names + counts) and changes
# nothing. `make demo-reset CONFIRM=yes` performs the reset.
#
# Safety contract (docs/DECISIONS.md ADR-032):
#   * refuses to run unless the kubectl context is a LOCAL kind cluster and the
#     namespace is `urumi` (guard against prod)
#   * never runs helm, never deletes a Secret or a PVC; the only cluster object it
#     mutates is the demo-notes Deployment, whose note store is in-memory - a
#     restart IS the official "delete all notes" operation for that upstream
#   * never prints a credential: the Woo Consumer Key/Secret, the gateway admin
#     password, the notes bearer token and the Fernet key stay inside the pods
#     that already hold them
#
# What it deletes / keeps is decided by scripts/demo-seeds.json (auditable) and the
# two in-pod workers it drives:
#   scripts/demo-reset-woo.py   (woo-mcp pod)    Woo REST products + orders
#   scripts/demo-reset.py       (gateway pod)    audit_logs, tool_permissions,
#                                               non-admin users/keys,
#                                               notes count, demo users, verification
#
# Usage:
#   scripts/demo-reset.sh [--with-demo-users] [--check-only]
#   CONFIRM=yes scripts/demo-reset.sh [--with-demo-users]
#   make demo-reset                       # dry run
#   make demo-reset CONFIRM=yes           # perform

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS="${NAMESPACE:-urumi}"
EXPECTED_CONTEXT="${CONTEXT:-kind-urumi}"
CONFIRM="${CONFIRM:-no}"
WITH_DEMO_USERS=0
CHECK_ONLY=0

usage() {
    cat <<'EOF'
usage: scripts/demo-reset.sh [--with-demo-users] [--check-only]

  (no flags)     DRY RUN - prints what would be deleted, changes nothing
  CONFIRM=yes    performs the reset (Woo products/orders, audit_logs,
                 tool_permissions back to allow-all, non-admin
                 users + their API keys, all notes), then verifies 3 Connected
                 upstreams and tools/list = 11 tools
  --with-demo-users   additionally create demo-a@urumi.local (admin) and
                 demo-b@urumi.local (member) with fresh API keys; the credentials
                 are printed ONCE to this terminal and never stored
  --check-only   only run the safety guard (context = local kind, ns = urumi)

Environment: NAMESPACE (must stay `urumi`), CONTEXT (default kind-urumi), CONFIRM
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --with-demo-users) WITH_DEMO_USERS=1 ;;
        --check-only) CHECK_ONLY=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "demo-reset: unknown argument: $1" >&2; usage >&2; exit 64 ;;
    esac
    shift
done

warn() { printf 'demo-reset: %s\n' "$*" >&2; }
die() { local code="${2:-1}"; warn "$1"; exit "$code"; }

# ------------------------------------------------------------------ the guard
guard() {
    command -v kubectl >/dev/null 2>&1 || die "kubectl not found in PATH" 2

    local ctx server
    ctx="$(kubectl config current-context 2>/dev/null || true)"
    [ -n "$ctx" ] || die "no current kubectl context - refusing to guess" 2

    case "$ctx" in
        kind-*) ;;
        *) die "REFUSING to run: kubectl context '$ctx' is not a local kind cluster (expected kind-*, e.g. '$EXPECTED_CONTEXT'). This reset only ever runs against the local demo cluster." 2 ;;
    esac

    if [ "$ctx" != "$EXPECTED_CONTEXT" ]; then
        warn "context '$ctx' differs from the project default '$EXPECTED_CONTEXT' (a second kind cluster?)"
    fi

    # kind always serves the API server on loopback; a remote (VPS/k3s/prod) server
    # can never pass this check even if someone renamed its context.
    server="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null || true)"
    case "$server" in
        https://127.0.0.1:*|http://127.0.0.1:*|https://localhost:*|http://localhost:*) ;;
        *) die "REFUSING to run: cluster API server '$server' is not local (kind serves 127.0.0.1)." 2 ;;
    esac

    [ "$NS" = "urumi" ] || die "REFUSING to run: namespace must be 'urumi' (got '$NS') - this reset only knows the demo dataset." 2

    echo "guard OK: context=$ctx (kind, api=$server) namespace=$NS"
}

guard

if [ "$CHECK_ONLY" = "1" ]; then
    echo "guard OK - nothing else ran (--check-only)"
    exit 0
fi

GW_POD="$(kubectl get pods -n "$NS" -l app=gateway -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
WOO_POD="$(kubectl get pods -n "$NS" -l app=woo-mcp -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
[ -n "$GW_POD" ] || die "no gateway pod found in namespace $NS" 1
[ -n "$WOO_POD" ] || die "no woo-mcp pod found in namespace $NS" 1

SEEDS_JSON="$(cat "$SCRIPT_DIR/demo-seeds.json")"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/demo-reset.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

# Read-only kubectl calls (get pods / exec) plus, on a confirmed run, `rollout
# restart` + `rollout status` on the demo-notes Deployment only. No helm, no
# Secret/PVC operations anywhere in this file.

run_woo() {
    kubectl exec -n "$NS" "$WOO_POD" -c woo-mcp -- \
        python3 -c "$(cat "$SCRIPT_DIR/demo-reset-woo.py")" "$@" --seeds-json "$SEEDS_JSON"
}

run_gateway() {
    kubectl exec -n "$NS" "$GW_POD" -c gateway -- \
        python3 -c "$(cat "$SCRIPT_DIR/demo-reset.py")" "$@"
}

# emit <json-out> <label> <command...>: run a worker, print its human output, keep only
# its SUMMARY_JSON line for the final summary. The worker output is held in memory and
# never written to disk, so the --with-demo-users credentials are printed once to the
# terminal and nowhere else.
emit() {
    local json_out="$1" label="$2" out rc
    shift 2
    echo "== $label =="
    rc=0
    out="$("$@")" || rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "(worker failed with exit $rc - nothing after it was attempted)"
        exit 1
    fi
    printf '%s\n' "$out" | grep -v '^SUMMARY_JSON ' || true
    printf '%s\n' "$out" | grep '^SUMMARY_JSON ' | sed 's/^SUMMARY_JSON //' >"$json_out" || true
}

if [ "$CONFIRM" = "yes" ]; then
    MODE="CONFIRMED - performing the reset"
else
    MODE="DRY RUN (default) - nothing will be deleted"
fi

echo "== demo-reset =="
echo "mode:      $MODE"
echo "cluster:   $(kubectl config current-context)  namespace: $NS"
echo "pods:      gateway=$GW_POD  woo-mcp=$WOO_POD"
[ "$WITH_DEMO_USERS" = "1" ] && echo "demo users: --with-demo-users (fresh keys printed once below)"
echo ""

# ---- phase 1: always read-only ----
emit "$WORK/woo-plan.json" "WooCommerce: products + orders (woo-mcp pod)" run_woo --dry-run
echo ""
emit "$WORK/gw-plan.json" "Gateway: audit_logs, users, api_keys, servers, notes" run_gateway --dry-run

# ---- phase 2: perform (confirmed runs only) ----
if [ "$CONFIRM" = "yes" ]; then
    echo ""
    emit "$WORK/woo.json" "WooCommerce reset (confirmed)" run_woo
    echo ""
    GW_ARGS=(--reset)
    if [ "$WITH_DEMO_USERS" = "1" ]; then
        GW_ARGS+=(--with-demo-users)
    fi
    emit "$WORK/gw.json" "Gateway reset (confirmed)" run_gateway "${GW_ARGS[@]}"

    echo ""
    echo "== Notes upstream: restart to clear the in-memory note store =="
    kubectl rollout restart deployment/urumi-demo-notes -n "$NS"
    # The health probe below must not race the restart: wait for the new pod to be
    # Ready first, or 'notes Unreachable' would be a false alarm.
    kubectl rollout status deployment/urumi-demo-notes -n "$NS" --timeout=180s

    echo ""
    emit "$WORK/verify.json" "Verification: 3 upstreams Connected + tools/list = 11 tools" run_gateway --verify
fi

# ---- phase 3: summary (both modes) ----
echo ""
if [ "$CONFIRM" = "yes" ]; then
    echo "== demo-reset summary =="
else
    echo "== demo-reset summary (DRY RUN - nothing was deleted) =="
fi
python3 - "$WORK" <<'PY' || echo "(summary unavailable: python3 not found on this host)"
import json
import pathlib
import sys

work = pathlib.Path(sys.argv[1])


def load(name):
    try:
        return json.loads((work / name).read_text())
    except Exception:
        return {}


# the executed summaries win; a dry run only ever ends up with the *-plan ones
woo = load("woo.json") or load("woo-plan.json")
gw = load("gw.json") or load("gw-plan.json")
vf = load("verify.json")
dry = not (vf or (gw and gw.get("mode") == "reset"))

print("deleted (dry run: would delete):" if dry else "deleted:")
if woo:
    if dry:
        print(
            f"  WooCommerce: {woo.get('products_planned', 0)} test products, "
            f"{woo.get('orders_planned', 0)} orders"
        )
    else:
        print(
            f"  WooCommerce: {woo.get('products_deleted', 0)} test products "
            f"({woo.get('products_planned', 0)} planned, {woo.get('products_already_gone', 0)} already gone), "
            f"{woo.get('orders_deleted', 0)} orders ({woo.get('orders_planned', 0)} planned)"
        )
if gw:
    if gw.get("mode") == "reset":
        print(
            f"  Gateway: {gw.get('audit_rows_deleted', 0)} audit_logs rows, "
            f"{len(gw.get('users_deleted', []))} non-admin users, {gw.get('keys_deleted', 0)} api keys, "
            f"{gw.get('perm_rules_deleted', 0)} tool-permission rules cleared"
        )
        for email in gw.get("users_deleted", []):
            print(f"    deleted user: {email}")
    else:
        print(
            f"  Gateway: {gw.get('audit_rows_planned', 0)} audit_logs rows, "
            f"{len(gw.get('users_planned', []))} non-admin users, "
            f"{gw.get('member_keys_planned', 0)} api keys"
        )
if isinstance(gw.get("notes_count"), int):
    verb = "would clear" if dry else "cleared"
    print(f"  Notes: {verb} all {gw['notes_count']} note(s) (demo-notes restart)")

print("kept:")
if gw and gw.get("mode") == "reset":
    print(f"  admin user(s): {', '.join(gw.get('admins_kept', [])) or 'none'}")
    print(f"  admin-owned api_keys: {gw.get('admin_keys_kept', 0)} (spec: only non-admin keys are deleted)")
    print(f"  upstream servers (never touched): {', '.join(gw.get('servers_kept', [])) or 'none'}")
elif gw:
    print(f"  admin user(s): {', '.join(gw.get('admins_kept', [])) or 'none'}")
    print(f"  admin-owned api_keys: {gw.get('admin_keys_kept', 0)}")
    print(f"  upstream servers (never touched): {', '.join(s['slug'] for s in gw.get('servers', [])) or 'none'}")
if woo.get("products_kept"):
    for kept in woo["products_kept"]:
        print(f"  kept product: #{kept.get('id')} {kept.get('name')} (sku {kept.get('sku')})")
print("  store settings incl. COD, all Kubernetes Secrets, all PVCs, the Helm release")
if vf:
    print(
        f"  verification: {vf.get('servers_connected', 0)}/{vf.get('servers_expected', 0)} upstreams Connected, "
        f"tools/list = {vf.get('tools_listed', 0)} tools {vf.get('tools_by_prefix', {})}"
    )
    if vf.get("failures"):
        print(f"  FAILURES: {vf['failures']}")
PY

if [ "$CONFIRM" != "yes" ]; then
    echo ""
    echo "DRY RUN: nothing was deleted, restarted or created."
    echo "re-run with CONFIRM=yes (i.e. 'make demo-reset CONFIRM=yes') to perform this reset."
    exit 0
fi

if [ -f "$WORK/verify.json" ] && grep -q '"ok": *false' "$WORK/verify.json"; then
    echo "demo-reset: verification FAILED (see above)"
    exit 5
fi

echo ""
echo "demo-reset done."
