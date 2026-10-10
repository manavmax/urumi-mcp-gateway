# 05a — Day 0-2 Completion Checklist (verified live on Kind)

> **Status: DONE AND VERIFIED** on `kind-urumi` (rev 12, `helm list -n urumi` = `deployed`), 2026-10-10.
> Store is live at `http://store.127.0.0.1.nip.io` (title "Urumi Store"), COD checkout + Woo REST verified with generated CK/CS in `woo-secrets`.

## How to reproduce / re-verify

```bash
make kind-up
make ingress                 # kubectl apply ingress-nginx for kind
make helm-local              # secrets-local + helm upgrade --install (hooks run wp-setup)
make verify-store            # helm lint + ps + wp-setup logs + store curl + woo-secrets
make verify-cod              # COD offered at checkout (Store API) + COD option value
```
Single-shot checks:
```bash
helm lint ./helm -f helm/values-local.yaml && helm lint ./helm -f helm/values-prod.yaml
kubectl get pods,svc,ingress,pvc,jobs,networkpolicy -n urumi
kubectl get job -n urumi                          # urumi-wp-setup: Complete 1/1
kubectl logs -n urumi -l app=wp-setup --tail=100
curl -s -H "Host: store.127.0.0.1.nip.io" http://localhost/ | grep -o "<title>.*</title>"   # <title>Urumi Store</title>
curl -s -H "Host: store.127.0.0.1.nip.io" http://localhost/wp-json/wc/v3/products \
  -u "$CK:$CS" | head -c 120                     # CK/CS from woo-secrets
```

## Day 0 — Pre-Day (repo & tooling)

- [x] `git init` + README skeleton + `.gitignore` (`.env`, `*.key`, `__pycache__`, `*.pem`, `*-secrets.yaml`)
- [x] Helm chart structure per `docs/06_KUBERNETES_AND_HELM.md` (umbrella `urumi 0.1.0 / 1.0.0`)
- [x] `kind-config.yaml` (control-plane, 80/443 port mappings)
- [x] `Makefile`: `kind-up`, `kind-down`, `ingress`, `lint`, `template`, `secrets-local`, `helm-local`, `helm-prod`, `logs`, `ps`, `port-forward`, **new** `verify-store`, `wp-logs`
- [x] Pinned deps: `requirements.txt` (`fastapi==0.115.*`, `mcp==1.12.*`, `httpx==0.27.*`, `sqlalchemy[asyncio]==2.0.*`, `asyncpg`, `argon2-cffi`, `cryptography`, `openai==1.*`, ...)
- [x] `docker-compose.yml` for a fast local loop without Kind
- [x] `helm/values.schema.json` (type/pattern validation for values) — new
- [x] `helm/templates/NOTES.txt` (post-install verification commands) — new
- [x] `ingress-nginx` installed on `kind-urumi` (kind provider manifest)
- [ ] `git commit` — still 0 commits (see "Left for later")

## Days 1-2 — Store on Kind (Layer 1)

- [x] WordPress + MariaDB Helm templates + PVCs + Services + Ingress (`store.127.0.0.1.nip.io`)
- [x] `wp-setup` Helm hook Job (post-install/upgrade, `before-hook-creation,hook-succeeded`):
  - `wp core install` (retry loop, URL = store host)
  - WooCommerce **9.4.2 pinned** install+activate (compatible with WP 6.6/PHP 8.2)
  - `wp wc tool run install_pages`, permalinks `/%postname%/`
  - COD gateway enabled with the **full gateway settings** (all 6 keys via `WC_Payment_Gateways` form defaults, not a partial option write) — verified offered at checkout on a clean install
  - 2 products seeded (Urumi Classic Tee $29.99 SKU `URUMI-TEE-001`, Urumi Hoodie $59.99 `URUMI-HOODIE-001`) with `_stock_status`/`_visibility`/`_manage_stock` + lookup-table regen
  - MU plugin `urumi-internal-rest.php` (see gotcha #3)
  - Woo Consumer Key/Secret generated (`wc_api_hash`), rotated idempotently, written to `woo-secrets` via the K8s API (SA + Role/RoleBinding, `pods/exec` not needed)
  - Final verification step hits `wc/v3/products` with CK/CS
- [x] Woo CK/CS stored in `woo-secrets` Secret (never in values)
- [x] Manual test passed: storefront 200, COD order created via REST (`payment_method_title: "Cash on delivery"`), order listed back; on the clean install COD is offered at checkout with no manual save (`make verify-cod` -> `"payment_methods":["cod"]`)
- [x] Probes + resources + NetworkPolicy on all workloads
- [x] Exit: `curl store.127.0.0.1.nip.io` works; `helm lint` passes (local + prod)

## Placeholders added for Days 3-9 (kept lint-clean)

- [x] `deployment-gateway.yaml` + `service-gateway.yaml` (`gateway.enabled`, `/healthz` `/readyz`, `gateway-secrets` refs)
- [x] `deployment-woo-mcp.yaml` + `service-woo-mcp.yaml` (`wooMcp.enabled`, `woo-secrets` refs, private tier)
- [x] `deployment-dashboard.yaml` + `service-dashboard.yaml` (`dashboard.enabled`, nginx-style probes)
- [x] `networkpolicy.yaml`: `allow-gateway-to-woo-mcp` + `allow-gateway-egress-to-woo-mcp` (render only when `wooMcp.enabled`)

---

## Gotchas solved here (do not relearn these)

1. **`operational mariadb/wordpress `chown` failures on local-path PVCs** — the images run as root and need to `chown` the mounted volume (33:33 and 999:999 in rancher local-path). `capabilities: {drop: [ALL]}` makes them crash-loop. Fix applied: `container securityContext runAsUser: 0 + allowPrivilegeEscalation: true + add: [CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID]`. Documented in `SYSTEM_DESIGN_AND_TRADEOFFS.md` as a dev-VM-only relaxation.
2. **kubelet follows redirects in HTTP probes** — `/wp-login.php` 302s to `/wp-admin/install.php`, which takes ~6s cold; the startup probe (default 1s timeout) fails and the pod never starts. Fix: readiness/liveness use the static `/readme.html`, startup uses `/wp-login.php` with `timeoutSeconds: 20`, `failureThreshold: 30`.
3. **WooCommerce only sends consumer key/secret Basic auth when `is_ssl()`** — Basic auth over plain in-cluster HTTP silently returns 401 `woocommerce_rest_cannot_view`. Fix: MU plugin (created by the setup job) sets `$_SERVER['HTTPS']='on'` **only for `/wp-json/` requests**. Side effect: REST response links are `https://...` (correct for prod, cosmetic locally). Do NOT "fix" this by disabling TLS later.
4. **Plugin/core version parity** — installing latest WooCommerce (11.x) on WP 6.6/PHP 8.2 causes a fatal (`register_block_template()` undefined) that also kills wp-cli bootstrap. Fix: `wp core download --version=<wp-image major.minor>` and `wpSetup.wooVersion: 9.4.2`, plus a pre-boot step that deletes a mismatched `wp-content/plugins/woocommerce` **before** any `wp` command runs.
5. **`terraform`-style shared PVC + WP core** — only `wp-content` is on the PVC; core lives in the pod image. The setup job therefore downloads core and writes `wp-config.php` in its own filesystem while sharing the DB + `wp-content`, so its actions apply to the live site. Do not mount the same PVC read-write on two pods and expect parity of core.
6. **`set -o pipefail` fails in the WP images** (dash `/bin/sh`). Use `set -eu` in job scripts.
7. **kind NetworkPolicy IS enforced** — the wp-setup job needs explicit egress for: `wordpress:80`, `mariadb:3306`, DNS (kube-dns), public 443/80 (wordpress.org downloads, `0.0.0.0/0` except RFC1918 + `fc00::/7`), **and the K8s API** (`10.96.0.0/12:443` **and** `global.nodeCIDR` `172.18.0.0/16:443,6443` — ClusterIP traffic is DNAT-ed to a node IP, so blocking the node CIDR silently breaks the K8s API call that stores `woo-secrets`; symptom is `000` from curl, never an HTTP error).
8. **Job restart policy** — `restartPolicy: Never` + `backoffLimit: 1` keeps failed pods for log inspection (`hook-succeeded` delete policy still removes successful ones).
9. **`wp core download` needs egress 443** — the job's init gate now polls the static `/readme.html` (not `/wp-login.php`) so a PHP fatal cannot deadlock setup.
10. **`docker-compose.yml` / colima** — the colima VM was stopped at session start; `colima start --cpu 2 --memory 4 --disk 40` restores docker/kind. Kept running.
11. Note the default StorageClass in this cluster is `standard` (rancher local-path); `local-path` only exists on k3s → `values-prod.yaml` keeps `local-path` and is untouched.
12. **Admin credentials can drift from `values.yaml`** — the user was created by whichever install attempt first succeeded against a recycled PVC, so `values.yaml` was not the source of truth and `admin`/`admin123` failed to log in. Fix: the setup Job now syncs the admin password on every run (`wp user update "$ADMIN_USER" --user_pass=...`) after install, so the chart is authoritative. When a login keeps failing, check the DB row (`SELECT user_login, user_registered FROM wp_users`) before assuming the value file is wrong.
13. **COD settings must be written in the same shape WooCommerce writes** — hand-writing only `{"enabled":"yes","title":...,"description":...,"instructions":...}` (4 of 6 keys) is not a form WooCommerce ever produces, and the missing keys made the gateway behave differently at checkout than in Settings > Payments; only a manual untick/tick/save (which rewrites all 6) fixed it. Fix: the job builds the option from the **gateway's own `form_fields` defaults** via `WC_Payment_Gateways` and overrides enabled/title/description/instructions. Result is identical to an admin save: `enabled, title, description, instructions, enable_for_methods, enable_for_virtual` (verified by diff), configurable via `wpSetup.cod.*`.
14. **WooCommerce 9.x installs the BLOCK checkout** — the payment method list is rendered client-side from the Store API (`GET /wp-json/wc/store/v1/cart` → `payment_methods`), so verifying "COD at checkout" with the classic `?wc-ajax=update_order_review` nonce flow shows nothing (no `update_order_review_nonce` is printed on the page). Verify with the Store API instead (`make verify-cod` does both; the classic path is a documented fallback).

## Verified clean install (fresh `kind` cluster, no recycled PVC)

```bash
make ingress && make helm-local && make verify-cod
```
Result on a from-scratch cluster (rev 1): store 200 `<title>Urumi Store</title>`, admin login OK, `woocommerce_cod_settings` = full 6-key array, Store API returns `"payment_methods":["cod"]` with `"items_count":1` — **COD offered at checkout with no manual save**.

## Left for later / notes to future self

- **Commit the repo**: still `git status` clean-ish but **0 commits**. Before any further work: `git add -A && git commit -m "Day 0-2: store on kind"` (the `Urumi AI FDE Internship - Round 1_ MCP Gateway on Kubernetes.pdf` is a large binary — decide whether to keep it tracked).
- **`gateway-secrets` FERNET key**: `make secrets-local` generates a random one each run unless the secret already exists (lookup-guarded templates). For a stable dev key, create the secret once manually.
- **`dashboard.127.0.0.1.nip.io`** currently proxies to WordPress (dashboard not shipped yet) — intentional placeholder, documented in `helm/templates/ingress.yaml`.
- **Postgres is deployed but unused** until Day 5-7; keep it (it is the gateway's DB and mirrors prod).
- **`src/{gateway,woo-mcp,dashboard}` still empty** — next up is Days 3-4 (`src/woo-mcp`): FastAPI + `mcp` SDK Streamable HTTP, 6 tools via `httpx` to `wc/v3`, CK/CS from `woo-secrets`, probes `/healthz` `/readyz`, NetworkPolicy already staged.
- **kube-linter**: binary not available on this machine (Day 10 item); `helm lint` + `helm template` review is the current substitute.
