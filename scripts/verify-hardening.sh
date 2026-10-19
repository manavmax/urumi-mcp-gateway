#!/usr/bin/env bash
# Hardening verification (security pass, ADR-041..047) — REAL cluster probes only.
#
#   bash scripts/verify-hardening.sh
#
# Prints, per workload: effective uid (kubectl exec id), capability drop, read-only
# root, SA token mount absence, securityContext fields; then NetworkPolicy probes
# (throwaway pod blocked from every private tier port; gateway reaches each
# upstream), the login lockout probe (429 after N attempts), and the security
# header probe on the dashboard and the gateway API.
set -u
NS=${NAMESPACE:-urumi}
PASS=0; FAIL=0
ok()   { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }

echo "== 1. Per-workload pod security (live cluster) =="
kubectl get pods -n "$NS" -o json > /tmp/urumi-hardening-pods.json
mapfile -t ROWS < <(python3 - <<'PYEOF'
import json
for p in json.load(open("/tmp/urumi-hardening-pods.json"))["items"]:
    spec = p["spec"]
    app = next((v for k, v in p["metadata"].get("labels", {}).items() if k == "app"), "?")
    for c in spec["containers"]:
        sc = c.get("securityContext", {})
        tok = "false" if spec.get("automountServiceAccountToken") is False else "true"
        drops = ",".join(sc.get("capabilities", {}).get("drop", []))
        seccomp = sc.get("seccompProfile", {}).get("type", "")
        sa = spec.get("serviceAccountName", "default")
        print("|".join([p["metadata"]["name"], c["name"], app,
                        str(sc.get("runAsUser")), str(sc.get("runAsGroup")),
                        str(sc.get("runAsNonRoot")), drops,
                        str(sc.get("readOnlyRootFilesystem")), seccomp,
                        tok, sa]))
PYEOF
)
printf "  %-22s %-11s %-9s %-10s %-9s %-9s %-15s %s\n" POD/CONTAINER APP UID CAPS-DROP RO-ROOT SECCOMP TOKEN SA
for row in "${ROWS[@]}"; do
  IFS='|' read -r pod cont app uid gid nonroot drops roroot seccomp tok sa <<< "$row"
  printf "  %-22s %-11s %-9s %-10s %-9s %-9s %-15s %s\n" "${pod%%-*}" "$app" "uid=$uid" "${drops:-none}" "$roroot" "$seccomp" "$tok" "$sa"
done
for row in "${ROWS[@]}"; do
  IFS='|' read -r pod cont app uid gid nonroot drops roroot seccomp tok sa <<< "$row"
  live_uid=$(kubectl exec -n "$NS" "$pod" -c "$cont" -- id -u 2>/dev/null || echo "?")
  [ "$live_uid" = "$uid" ] && [ "$uid" != "0" ] && ok "$app: runs as non-root uid $live_uid (declared $uid)" || bad "$app: uid mismatch (live=$live_uid declared=$uid)"
  echo "$drops" | grep -q ALL && ok "$app: ALL capabilities dropped" || bad "$app: capabilities not dropped"
  [ "$seccomp" = "RuntimeDefault" ] && ok "$app: seccompProfile RuntimeDefault" || bad "$app: seccomp missing"
  if [ "$tok" = "false" ]; then
    kubectl exec -n "$NS" "$pod" -c "$cont" -- ls /var/run/secrets/kubernetes.io/serviceaccount >/dev/null 2>&1 \
      && bad "$app: automount=false but token dir EXISTS" || ok "$app: SA token not mounted"
  else
    echo "  NOTE  $app: SA token mounted (wp-setup hook: writes woo-secrets via the K8s API, Role-scoped)"
  fi
done
echo "  -- readOnlyRootFilesystem (declared per workload; false = documented residual) --"
for row in "${ROWS[@]}"; do
  IFS='|' read -r pod cont app uid gid nonroot drops roroot seccomp tok sa <<< "$row"
  echo "  $app: readOnlyRootFilesystem=$roroot"
done

echo "== 2. NetworkPolicy enforcement (CNI) =="
kubectl run urumi-np-probe --image=busybox:1.36 --restart=Never -n "$NS" --command -- sh -c \
  'for t in "urumi-woo-mcp 8000" "urumi-demo-notes 8000" "urumi-demo-time 8000" "urumi-postgres 5432" "urumi-mariadb 3306"; do
     set -- $t
     if nc -z -w3 "$1" "$2" 2>/dev/null; then echo "$1:$2 CONNECTED"; else echo "$1:$2 BLOCKED"; fi
   done' >/dev/null 2>&1
kubectl wait --for=condition=Ready pod/urumi-np-probe -n "$NS" --timeout=60s >/dev/null 2>&1
sleep 16
OUT=$(kubectl logs urumi-np-probe -n "$NS" 2>/dev/null)
kubectl delete pod urumi-np-probe -n "$NS" --wait=false >/dev/null 2>&1
for target in woo-mcp demo-notes demo-time postgres mariadb; do
  echo "$OUT" | grep -q "urumi-$target.*BLOCKED" && ok "throwaway pod -> $target BLOCKED" || bad "throwaway pod -> $target NOT blocked"
done

GW=$(kubectl get pods -n "$NS" -l app=gateway -o jsonpath='{.items[0].metadata.name}')
for peer in "urumi-woo-mcp:8000" "urumi-demo-notes:8000" "urumi-demo-time:8000" "urumi-postgres:5432"; do
  host=${peer%:*}; port=${peer#*:}
  if kubectl exec -n "$NS" "$GW" -- python3 -c "
import socket,sys
s=socket.socket(); s.settimeout(4)
try: s.connect(('$host',$port)); sys.exit(0)
except OSError: sys.exit(1)
finally: s.close()" 2>/dev/null; then ok "gateway -> $peer reachable"; else bad "gateway -> $peer BLOCKED (must succeed)"; fi
done

echo "== 3. Login lockout (429 after N attempts) =="
# Probe from a THROWAWAY pod (fresh source IP per run, randomized email) so
# repeated runs are never locked out by the previous run's per-IP/per-user
# counters. A scoped egress NetworkPolicy lets the probe reach ONLY the gateway
# (default-deny otherwise) and is deleted right after, together with the pod.
LOCK_EMAIL="hardening-probe-$RANDOM@urumi.local"
kubectl run urumi-lock-probe --image=busybox:1.36 --restart=Never -n "$NS" --labels=run=hardening-probe --command -- sh -c \
  "sleep 1; for i in 1 2 3 4 5 6 7; do
     wget -q -S -O /dev/null --post-data='{\"email\":\"$LOCK_EMAIL\",\"password\":\"w'\$i'\"}' \
       --header='Content-Type: application/json' http://urumi-gateway:8000/api/auth/login 2>&1 \
     | grep -oE 'HTTP/1.1 [0-9]+' | tail -n1
   done; echo SEQ-DONE" >/dev/null 2>&1
cat <<'NPEOF' | kubectl apply -f - >/dev/null
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hardening-probe-egress
  namespace: urumi
spec:
  podSelector:
    matchLabels:
      run: hardening-probe
  policyTypes: ["Egress"]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: gateway
      ports:
        - protocol: TCP
          port: 8000
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
NPEOF
kubectl wait --for=condition=Ready pod/urumi-lock-probe -n "$NS" --timeout=60s >/dev/null 2>&1
for _ in $(seq 1 30); do kubectl logs urumi-lock-probe -n "$NS" 2>/dev/null | grep -q SEQ-DONE && break; sleep 3; done
LOCK_CODES=$(kubectl logs urumi-lock-probe -n "$NS" 2>/dev/null | grep -E "^HTTP/1.1 [0-9]+" | awk '{print $2}' | tr '\n' ' ')
kubectl delete pod urumi-lock-probe -n "$NS" --wait=false >/dev/null 2>&1
kubectl delete netpol hardening-probe-egress -n "$NS" >/dev/null 2>&1
echo "  login codes: $LOCK_CODES"
FIRST429=$(echo "$LOCK_CODES" | tr ' ' '\n' | grep -n 429 | head -1 | cut -d: -f1)
COUNT401=$(echo "$LOCK_CODES" | tr ' ' '\n' | grep -c 401)
if [ -n "$FIRST429" ] && [ "$COUNT401" -ge 1 ] && [ "$FIRST429" -gt "$COUNT401" ]; then
  ok "lockout: $COUNT401 x 401 then 429 from attempt $FIRST429 (cap respected)"
else
  bad "lockout probe did not return 401->429 (codes: $LOCK_CODES)"
fi

echo "== 4. Security headers (dashboard nginx + gateway API) =="
for check in "http://dashboard.127.0.0.1.nip.io/ dashboard" "http://dashboard.127.0.0.1.nip.io/api/healthz gateway-api"; do
  set -- $check; url=$1; label=$2
  HDRS=$(curl -sI "$url")
  for h in "content-security-policy" "x-content-type-options" "referrer-policy" "x-frame-options"; do
    echo "$HDRS" | grep -qi "^$h:" && ok "$label: $h present" || bad "$label: $h MISSING"
  done
  echo "$HDRS" | grep -i "^content-security-policy" | grep -q "frame-ancestors 'none'" && ok "$label: frame-ancestors 'none'" || bad "$label: frame-ancestors missing"
done

echo "== 5. Secrets in pod logs (key-shaped strings) =="
TOTAL=0
for p in gateway dashboard woo-mcp demo-time demo-notes mariadb wordpress postgres; do
  POD=$(kubectl get pods -n "$NS" -l app=$p -o jsonpath='{.items[0].metadata.name}')
  N=$(kubectl logs -n "$NS" "$POD" -c $p --tail=2000 2>/dev/null | grep -cE "urumi_sk_[A-Za-z0-9_-]{20,}|ck_[a-f0-9]{16,}|cs_[a-f0-9]{16,}|AIza[A-Za-z0-9_-]{30}" || true)
  TOTAL=$((TOTAL+N))
done
[ "$TOTAL" -eq 0 ] && ok "0 key-shaped strings across all pod logs" || bad "$TOTAL key-shaped strings in pod logs"

echo ""
echo "== RESULT: $PASS passed, $FAIL failed =="
[ "$FAIL" -eq 0 ]
