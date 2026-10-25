# Urumi AI: MCP Gateway on Kubernetes

WooCommerce store + a team MCP gateway on Kubernetes + Helm, built as a take-home. One `/mcp` endpoint aggregates N Streamable-HTTP MCP servers behind deterministic `slug__tool` names, with a React dashboard (servers, members, keys, audit, chat), a chat agent that calls tools as the logged-in user, a provisioned multi-store system, hosted servers, and OAuth 2.1 for MCP clients. Take-home due 26 Oct 2026, 11:59 PM IST.

**Status:** complete and verified live: kind locally, k3s on a VPS since 2026-10-20 (Let's Encrypt production cert). `make test` green (gateway 419 passed + 2 skipped, woo-mcp 21, demo-mcp-time 8), `make lint` clean, `bash scripts/regress-core.sh` passes end to end.

## Architecture in 5 lines

1. **Store:** WordPress + WooCommerce + MariaDB on kind/k3s behind Ingress; a custom **woo-mcp** FastAPI server exposes 8 Woo tools over Streamable HTTP (ClusterIP only, gateway-only NetworkPolicy).
2. **Gateway (FastAPI):** MCP client to N upstreams + MCP server at `/mcp` + admin REST + chat agent + stores/hosted sync + OAuth; aggregates everything under `slug__tool` names with per-tool permissions, rate limits, SSRF validation and audit.
3. **Dashboard (React+Vite+TS):** Servers / Members / Keys / Audit / Chat / Metrics / Stores / Hosted; nginx non-root 101, strict CSP.
4. **Postgres:** users, keys, servers, tool cache, audit, permissions, stores, hosted, OAuth tables; async SQLAlchemy + Alembic, forward-only migrations.
5. **Provisioner (flag-gated):** turns dashboard actions into `store-<slug>` namespaces (helm CLI baked into its image); also hosts admin-supplied MCP server images.

## Docs

| Doc | Read when |
|---|---|
| `SYSTEM_DESIGN_AND_TRADEOFFS.md` | Root note: architecture, failure handling, stores, prod deltas, upgrade/rollback |
| `THREAT_MODEL.md` | Root note: assets, member/credential threats, SSRF, provisioner residual, OAuth |
| `docs/DECISIONS.md` | Full ADR log with rejected alternatives |
| `docs/01_ARCHITECTURE.md` | Diagrams and request flows |
| `docs/00_OVERVIEW_AND_TRACEABILITY.md` | Traceability matrix, DoD demo script, checklists |
| `docs/DEPLOY_VPS.md` | Stranger-runnable VPS walkthrough (k3s, DNS, TLS, first-install gotchas) |
| `docs/UPGRADE_ROLLBACK.md` | Rehearsed upgrade, rollback, pg_dump drill |
| `docs/ENDPOINT_MATRIX.md` | Every dashboard tile mapped to its endpoint |
| `docs/07_SECURITY_AND_THREAT_MODEL.md` | Long-form threat talk-track |

## Local setup (kind)

```bash
make kind-up            # kind create cluster --name urumi --config kind-config.yaml
make ingress            # ingress-nginx for kind
make helm-local         # chart-generated secrets + helm install (runs wp-setup hook, ~5 min on 2 cores)
make smoke-images       # build all images host-platform + per-image smoke test (no push)
make woo-mcp-image      # build + import woo-mcp into the kind node
make deploy             # rebuild + import gateway/dashboard/provisioner, restart pods
make verify-store verify-cod verify-mcp verify-gateway   # live gates
open http://store.127.0.0.1.nip.io        # storefront
open http://dashboard.127.0.0.1.nip.io    # dashboard (admin@urumi.local, see below)
```

`make lint` (helm lint x2 + chart parity + ruff) and `make test` (gateway + woo-mcp + demo-time suites) are the standing gates. Passwords: `make admin-password` (WordPress) and `make gateway-admin-password` (dashboard). The gateway admin password comes from the `gateway-admin` Secret; the LLM key is supplied by the operator (see below).

## Production setup (k3s on a VPS)

Full walkthrough: `docs/DEPLOY_VPS.md`. Shape:

1. k3s + ingress-nginx + cert-manager on the VPS; DNS A records for store/dashboard/apex.
2. Copy `helm/values-prod.example.yaml` to a PRIVATE uncommitted overlay; fill real domain, `nodeCIDR`, `trustedProxies`, storage class, GHCR image tags, and (only in that private file) the risky flags (`provisioner.enabled`, `stores.*`, `stores.tls.*`, `hostedServers.*` with `allowedRegistries: ghcr.io/<owner>`, `oauth.enabled`). Committed values ship everything OFF.
3. First install (NO `--wait`: the wp-setup hook creates the Secret woo-mcp waits for; helm runs hooks only after `--wait`): `make helm-prod-first`, then `kubectl wait --for=condition=complete job/urumi-wp-setup -n urumi`.
4. Every later upgrade: `make helm-prod` (adds `--rollback-on-failure --wait`). Take a `pg_dump` first. Upgrade/rollback story and the migration limit: `docs/UPGRADE_ROLLBACK.md` and the "Helm upgrade and rollback" section of `SYSTEM_DESIGN_AND_TRADEOFFS.md`.

## How to place an order

Open `store.<domain>` (local: `http://store.127.0.0.1.nip.io`), add to cart, block checkout, Cash on delivery (the only gateway, the default), Place order. The order is immediately visible in Woo Admin and via the gateway (`woo__list_orders`, or chat "what orders today?"). Guest checkout allowed, reviews off.

## Connect an external MCP client

1. Dashboard, Members page: create an API key (shown once).
2. Point the client at the gateway URL: `https://dashboard.<domain>/mcp` (local: `http://dashboard.127.0.0.1.nip.io/mcp`), `Authorization: Bearer <gateway key>`.
3. Tools are aggregated as `<server-slug>__<tool>`: `woo__list_orders`, `time__get_current_time`, `notes__add_note`. A member only sees tools their role permits.
4. OAuth clients (flag on): start at `/.well-known/oauth-protected-resource` on the gateway host; dynamic registration + PKCE + consent page; `scripts/phase7-oauth-gate.sh` is the scripted full-flow test.
5. MCP Inspector against woo-mcp directly: `kubectl port-forward -n urumi svc/urumi-woo-mcp 8000:8000`, connect to `http://localhost:8000/mcp`.

## Chat agent

Dashboard, Chat page: type "create product Urumi Tee $29.99" or "what orders today?". The gateway runs a server-side LLM loop as the logged-in user: it picks tools from the caller's filtered list, routes through the same permission/rate-limit/timeout/audit path as `/mcp`, streams tokens and tool chips via SSE, and every call is audited under the real user. Images can be attached (magic-byte validated, re-encoded, 15-minute TTL). The LLM endpoint is values (`gateway.llm.baseUrl` / `.model`, any OpenAI-compatible provider); the key is operator-supplied, never committed (ADR-022).

## Stores, hosted servers, feature flags

Everything risky is OFF in `helm/values.yaml`; only an explicit values file turns it on (values-local locally; a private prod overlay in prod):

| Flag | Default | What it gates |
|---|---|---|
| `provisioner.enabled` | false | the provisioner Deployment (stores + hosted servers) |
| `stores.maxPerUser/globalMax/maxConcurrent` | 2 / 12 / 2 | store namespace caps (values-local runs 1 concurrent: 2-core node) |
| `stores.tls.enabled` + `clusterIssuer` | false/"" | per-store cert-manager HTTP-01 certificates |
| `hostedServers.enabled` | false | admin hosts MCP servers by container image |
| `hostedServers.allowedRegistries` | "" (any) | registry prefix allowlist (prod overlay pins `ghcr.io/<owner>`) |
| `oauth.enabled` | false | OAuth 2.1 for `/mcp` (API keys keep working) |
| compact mode | opt-in per client | `X-Gateway-Mode: compact` header; chat auto-switches above `gateway.compactThreshold` |

With every flag off the core demo path is unchanged (regress-core gate proves it each phase).

- **Stores:** dashboard Stores page -> per-user storefront in its own `store-<slug>` namespace, tools appear as `<slug>__list_orders`, WooCommerce keys never leave the store namespace, per-namespace ResourceQuota/LimitRange, per-store TLS in prod.
- **Hosted servers:** admin adds an MCP server by image (tag/digest required, `:latest` refused, registry allowlist, no SA token, read-only rootfs, gateway-only ingress, DNS-only egress, capped resources); env values live in a cluster Secret and are never returned by any API.

## Verification scripts

| Gate | Command |
|---|---|
| Lint + chart parity + ruff | `make lint` |
| Unit tests | `make test` |
| Store + COD + MCP + gateway live gates | `make verify-store verify-cod verify-mcp verify-gateway` |
| Full DoD on kind | `bash scripts/regress-core.sh` |
| Security table + live probes | `bash scripts/verify-hardening.sh` |
| Chat LLM (streams, tool loop) | `make verify-llm` |
| OAuth full flow | `bash scripts/phase7-oauth-gate.sh` |
| Store UI/browser gates | `node scripts/verify-store.mjs`, `scripts/verify-store-contrast.mjs`, `scripts/verify-checkout.mjs` |
| Landing gates | `make landing-verify`, `make landing-graphics` (build, run the real nginx container on a free port, test, auto-cleanup) |
| Demo reset | `make demo-reset` (dry run) / `CONFIRM=yes` |

`make demo-reset` is dry-run by default, refuses non-kind contexts, uses official APIs only, and restores the demo state (29 seed products survive, audits/permissions/users reset).

## Stand-out items and where they live

| Item | Where it lives |
|---|---|
| Stores provisioner (per-user namespaces, cluster-derived readiness, teardown label) | `src/provisioner/`, `src/gateway/stores/`, `helm/store/`, dashboard Stores page |
| Hosted servers by container image (allowlist, no SA token, capped) | `src/gateway/hosted/`, `src/provisioner/`, dashboard Hosted page |
| OAuth 2.1 for MCP clients (dynamic registration, PKCE, rotating refresh) | `src/gateway/oauth/`, `src/gateway/routes/`, consent page in dashboard |
| Metrics from the audit table + `/metrics` | `src/gateway/gw_mcp/metrics.py`, `src/gateway/routes/stats.py`, dashboard Metrics page |
| Landing page (zero requests, strict CSP, config-driven) | `src/landing/`, `helm/templates/landing-*.yaml`, `scripts/landing-verify.mjs` |
| Store theme (29-product photo catalogue, honest UI, zero third-party requests) | `store/theme/urumi-store/`, `store/products.json`, `scripts/process-photos.py` |
| Tool permissions (per-role deny rules, one enforcement core) | `src/gateway/gw_mcp/permissions.py`, dashboard Permissions panel |
| Hardened NetworkPolicies + pod security (non-root, no tokens, default-deny) | `helm/templates/networkpolicy.yaml`, `helm/values.yaml` `podSecurity.*`, `scripts/verify-hardening.sh` |
| Upgrade/rollback rehearsal + startup schema gate | `docs/UPGRADE_ROLLBACK.md`, `src/gateway/db/schema_check.py` |

## Credentials and the LLM key (no committed secrets)

Every credential is chart-generated at install into a Secret (lookup-guarded, `helm.sh/resource-policy: keep`), never committed. `make admin-password` and `make gateway-admin-password` read the two dashboard passwords; the LLM key is applied by the operator with a hidden prompt (never shell history, files or logs):

```bash
printf 'Gemini API key (hidden): ' >&2
read -rs LLM_KEY
echo
kubectl -n urumi create secret generic gateway-llm --from-literal=OPENAI_API_KEY="$LLM_KEY" --dry-run=client -o yaml | kubectl apply -f -
unset LLM_KEY
kubectl get secret gateway-llm -n urumi -o jsonpath='{.data.OPENAI_API_KEY}' | base64 -d | wc -c   # length only, never print
```

An upgrade never wipes the key: the Secret value is `lookup`-guarded, `helm.sh/resource-policy: keep` survives uninstall, and only a different key changes the pod checksum (ADR-016/022). The chat endpoint/model are values (`gateway.llm.baseUrl`, `.model`, `.existingSecret`), not code. `make verify-llm` proves the live key. Chat text and attached images go to the configured LLM provider over public 443 (documented egress).

## Security posture (short)

Non-root everywhere with explicit uids, no SA tokens (one secrets-only exception), default-deny NetworkPolicies with explicit allows, login lockout, CSP, SSRF guard re-resolved at connect time, no secrets in git/values/logs. Full model and stated residuals: `THREAT_MODEL.md`. `bash scripts/verify-hardening.sh` prints the per-workload table (53 checks).

## Landing page (apex host)

`src/landing/` is a one-page static site (no build step, zero external requests, strict CSP, nginx uid 101 on 8080) served at the apex by the `landing` component (ADR-080/083/086). Design source of truth: `docs/LANDING_DESIGN.md`. Every GitHub link builds at runtime from the chart value `landing.repoUrl`, injected as `/landing-config.js`; "Beyond the brief" items are toggled in `src/landing/features.js`. Verify with `make landing-verify` and `make landing-graphics` (each builds the production image, runs it behind the real nginx with the strict CSP, and always cleans up).

## Known limitations (honest)

- **Helm rollback vs forward-only migrations:** the gateway runs `alembic upgrade head` on start and the startup schema gate compares `alembic_version` with the code's head. A helm rollback across a migration boundary leaves the DB ahead of the code, and the rolled-back gateway refuses to serve by design (ERROR log, `/readyz` unready, exit 3). Recovery is the pre-upgrade `pg_dump` or re-applying the newer release. `docs/UPGRADE_ROLLBACK.md` has the rehearsed drill.
- **Light-theme chart bar contrast:** dashboard light-mode chart bars measure 1.52:1 non-text contrast against the white card (pre-existing approved light design). The same data is always available as text (axis labels, tooltips, aria-labels, per-server table). Dark bars pass the 3:1 graphics minimum (3.43:1).
- **Provisioner ClusterRole:** cluster-scoped by necessity (RBAC cannot filter namespaces by label); a compromised provisioner ServiceAccount can read secrets cluster-wide and write workload kinds in any namespace, confined only by code-level label guards. Accepted for a single-node VPS; stated plainly in `THREAT_MODEL.md`.
- Rate limit, lockout and LLM cooldown counters are per replica (in-memory); gateway egress is open to public 443 for the LLM provider; the LLM provider sees chat text and images; readOnlyRootFilesystem stays false for wordpress/mariadb/wp-setup (non-root still holds).
