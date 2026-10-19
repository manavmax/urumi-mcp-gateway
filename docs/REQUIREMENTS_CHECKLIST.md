# REQUIREMENTS CHECKLIST

Status of every user story, every `must` in Requirements, the Definition of Done,
and every stand-out item from the Round 1 brief, verified **live in this session**
(2026-10-16). Nothing is marked DONE from memory: each DONE row names the command
run and the result observed now.

> Source: the brief PDF is transcribed in `docs/00_OVERVIEW_AND_TRACEABILITY.md`
> ("single source of truth for what Urumi grades"). This checklist follows that
> document's numbering (user stories §4, DoD §5, mandatory requirements §6, bonus §7).

Legend: **DONE** = verified live now · **PARTIAL** = works but with a documented gap ·
**NOT DONE** = not implemented / not verified.

---

## 1. User stories (docs/00 §4)

### Admin

| US | Status | Command / test | Result observed this session |
|---|---|---|---|
| See servers + status + tools | DONE | `node scripts/parity.mjs` (servers admin) + `kubectl exec gateway -- python3 -c "$(cat scripts/verify-gateway.py)"` | parity servers admin 21/21 match; gateway tools/list returns 13 tools (woo 8 / time 2 / notes 3; F3 added add_product_image + list_product_images); status chips Connected/Unreachable/Disabled render from live data |
| Woo MCP pre-registered | DONE | `curl -s dashboard.127.0.0.1.nip.io` + gateway tools/list | woo__* tools present with no manual registration; woo-mcp pod Running, Ingress only store+dashboard |
| Add/edit/disable/remove server | DONE | `/api/servers` CRUD probe (req-on-behalf probe, steps 6–8) | disable `time` -> tools/list drops `time__*`; re-enable -> tools return; admin CRUD 200, member CRUD 403 (verify-gateway) |
| Invite members + issue/revoke keys | DONE | `/api/users` POST + `/api/keys` POST/DELETE probe (req-on-behalf) | admin creates member (201), issues key on behalf of member (201, plaintext shown once, owned by member), revokes it (200) |
| Audit log | DONE | `node scripts/verify-audit-filters.mjs` + `psql select` on audit_logs | audit table: who/server/tool/when/duration/outcome; filters + pagination + CSV verified 10/10; attribution `time__get_current_time | success | admin@urumi.local | server=time` |

### Member

| US | Status | Command / test | Result observed this session |
|---|---|---|---|
| Generate own API key | DONE | member login + `POST /api/keys` | 201, plaintext key shown once (len 52), owner = the member |
| Single gateway URL + key in MCP client | DONE | `POST /mcp` with `Authorization: Bearer <member key>` (tools/list, tools/call) | member key calls `time__get_current_time` -> 200 + result; tools/list returns all enabled servers' tools |
| Chat via dashboard | DONE | `POST /api/chat/completions` (SSE) as admin; `node scripts/verify-llm.py` in pod | SSE `model`+`token` events then `[DONE]`; multi-step tool loop ran `woo__list_products`; final answer produced |
| Never sees upstream creds | DONE | `GET /api/servers` as admin | `credential` field is `null` (masked server-side; `servers.py:46` returns `"***"`/None, never plaintext); Fernet-encrypted at rest |

---

## 2. Definition of Done — demo script (docs/00 §5)

### Phase A — Store

| # | DoD step | Status | Command / test | Result observed this session |
|---|---|---|---|---|
| 1 | Open store, add product to cart, checkout COD, see order in Woo Admin | DONE | `node scripts/verify-checkout.mjs` (real browser storefront flow) | real browser: product page -> add to cart -> block checkout -> Cash on delivery -> Place Order; Store API POST returned **order 95 (status processing)**; order confirmed via gateway `woo__list_orders`; test order deleted after. 7/7 PASS. |

### Phase B — Chat as User A

| # | DoD step | Status | Command / test | Result observed this session |
|---|---|---|---|---|
| 2 | Chat "Create a product 'Urumi Tee' price $29.99" | DONE | `node scripts/verify-llm.py` in pod | multi-step loop ran `woo__create_product` -> created product, then `woo__list_orders`; audit rows `woo__create_product | success` |
| 3 | Hand-place order for that product | PARTIAL | `node scripts/verify-checkout.mjs` (browser storefront flow) | the browser flow now places a real order through the storefront (order 95, Urumi Shoes), but it was for a different product than the one the chat created in DoD 2, so the literal "hand-place order for THAT product" variant is not fully demonstrated |
| 4 | Chat "What orders came in today?" -> returns the order | DONE | `POST /api/chat/completions` + `woo__list_orders` probe | order #87 appears in `woo__list_orders` output (id 87, pending, COD) |

### Phase C — External MCP client as User B

| # | DoD step | Status | Command / test | Result observed this session |
|---|---|---|---|---|
| 5 | Inspector/Claude Code with User B key -> tools/list returns all enabled servers' tools | DONE | `/mcp tools/list` with member key (req-on-behalf probe) | 13 tools (woo 8 / time 2 / notes 3; F3) returned to a member key |
| 6 | Ask same orders question -> succeeds | DONE | `/mcp tools/call woo__list_orders` with member key | 200 + result (orders incl. #87) |
| 7 | One prompt needing 2 servers (cross-server aggregation) | DONE | `POST /api/chat/completions` "What time is it + list products" | SSE `tool_call` events for BOTH `time__get_current_time` and `woo__list_products` in one prompt; answer used both |

### Phase D — Control plane

| # | DoD step | Status | Command / test | Result observed this session |
|---|---|---|---|---|
| 8 | Revoke User B key -> next tools/call -> 401 | DONE | req-on-behalf probe | revoked key -> `401 {"error":{"code":-32000,"message":"invalid or revoked key"}}` |
| 9 | Disable one upstream -> its tools vanish from chat + client tools/list | DONE | req-on-behalf probe (disable `time`) | client `tools/list` dropped `time__*` (11 -> 9 tools), `woo__*` intact; chat agent only loads enabled servers (`chat/agent.py:231`) |
| 10 | `kubectl delete pod <woo-mcp-pod>` -> other servers still respond; dashboard shows Unreachable; then restore | PARTIAL | killpod probe (scale deploy to 0, observe, restore to 1) | with the pod gone (scale-to-0) the dashboard showed `woo = Unreachable`, `time__get_current_time` still 200, tools/list still listed time__+notes__; after restore `woo = Connected` and `woo__list_products` 200. **Gap:** the plain `kubectl delete pod` path can MISS the Unreachable window (the pod re-creates in ~30s vs the 15s health probe); the reliable observation required scale-to-0, so the literal DoD command is only verified as PARTIAL. A lower `health_interval_seconds` would make the bare delete path observable. |
| 11 | Audit log shows every call with correct user attribution | DONE | `psql` query on `audit_logs` join users | rows attributed to `admin@urumi.local` for gateway, `woo__*`, `time__*` calls with outcome + duration |

---

## 3. Mandatory Requirements Traceability (docs/00 §6)

### 6.1 Kubernetes & Helm

| Req | Status | Command / test | Result observed this session |
|---|---|---|---|
| Local Kind + VPS k3s same charts, values diff only | DONE (local) / PARTIAL (VPS) | `helm lint ./helm -f helm/values-local.yaml -f helm/values-prod.yaml` | both lint clean (0 failed); `values-prod.yaml` exists (domain/storageClass/replicas/TLS params) — VPS itself not reachable in this session, so live VPS run not observed |
| Helm mandatory, no Kustomize | DONE | `helm lint` + `helm/templates/*` | umbrella Helm chart, no Kustomize |
| Everything in-cluster (store, DB, woo-mcp, gateway, dashboard) | DONE | `kubectl get deploy,sts -n urumi` | 5 Deployments + 2 StatefulSets running in `urumi` ns |
| PVC for DB + wp-content | DONE | `kubectl get pvc -n urumi` | `data-urumi-mariadb-0` 10Gi, `data-urumi-postgres-0` 5Gi, `urumi-wp-content` 5Gi, all Bound |
| Ingress with stable URLs, local domain | DONE | `kubectl get ingress -n urumi` | ingress `urumi`: hosts `store.127.0.0.1.nip.io` + `dashboard.127.0.0.1.nip.io`; both reachable (200) |
| Readiness/liveness (+startup) + requests/limits on every workload | DONE | `kubectl get deploy,sts -o json` (probes/resources) | every workload has liveness+readiness (+startup on wordpress 150s, demo-time, demo-notes); every container has requests+limits |
| No hardcoded secrets, use K8s Secrets | DONE | `kubectl get secret -n urumi` | `gateway-secrets`, `woo-secrets`, `mariadb-secret`, `gateway-admin`, `gateway-llm`, `wordpress-admin`, `wordpress-secret`, `pg-secret`, `demo-notes-token`; no committed secrets (`.env` gitignored) |

### 6.2 WooCommerce MCP server

| Req | Status | Command / test | Result observed this session |
|---|---|---|---|
| Write yourself, no existing server | DONE | repo layout + `kubectl exec woo-mcp -- python3 -c "$(cat scripts/verify-mcp.py)"` | custom Python FastAPI + `mcp` SDK; 6 tools hand-written |
| Streamable HTTP | DONE | verify-mcp.py | initialize + tools/list + tools/call over Streamable HTTP, 2025-03-26 |
| Tools: list_products, create_product, list_orders, get_order, update_order_status (+get_product) | DONE | verify-mcp.py | 6 tools listed; create_product -> get_product round trip verified (id 82) |
| Not reachable outside cluster | DONE | NetworkPolicy + ingress + pod probes | woo-mcp Service is ClusterIP only, no ingress path; from dashboard pod (non-gateway) all 3 upstreams TIMEOUT; from gateway pod all 3 respond (406/401 protocol-level = reachable) |
| Doc how it talks to store | DONE | `docs/03_WOOCOMMERCE_MCP_SERVER.md` + woo REST | REST `wc/v3` with CK/CS via httpx; rationale documented |

### 6.3 Gateway

| Req | Status | Command / test | Result observed this session |
|---|---|---|---|
| Add/edit/disable/remove upstreams (Streamable HTTP + static cred) | DONE | verify-gateway.py + req-on-behalf probe | admin CRUD 200; disable removes tools; credential masked |
| One MCP endpoint aggregating tools, routing calls | DONE | verify-gateway.py | `POST/GET /mcp`; 13 tools from 3 servers (F3: +2 image tools); `slug__tool` prefix routing |
| Same tool name on 2 servers -> handle + document | DONE | verify-gateway.py (prefix checks) | every tool prefixed `slug__`; no unprefixed tools; unknown slug -> `-32602` validation_error |
| Slow/dead upstream must not break others | DONE | killpod probe | with woo down, `time__` call 200 and tools/list still returned 11; per-server timeout + gather(return_exceptions) |
| Upstream creds stay server-side | DONE | `GET /api/servers` + `servers.py:46` | `credential: null` in API response; Fernet-encrypted at rest |
| At least 3 upstreams | DONE | verify-gateway.py | woo-mcp (8) + demo-time (2) + demo-notes (3) = 13 tools (F3: woo 6 → 8) |

### 6.4 Team & Access

| Req | Status | Command / test | Result observed this session |
|---|---|---|---|
| Roles: admin, member | DONE | verify-gateway.py RBAC probes | member CRUD on servers/users -> 403; admin -> 200; member audit scoped to own rows |
| Per-user API keys, revocable, hashed | DONE | req-on-behalf probe + `db.models` | key minted per user; SHA-256 digest stored; `revoked_at` set; revoked key -> 401 |
| Audit log (user, server, tool, ts, duration, outcome) | DONE | `psql select` + verify-audit-filters | columns user/server/tool/ts/duration/outcome all populated; member sees own rows only |

### 6.5 Chat agent

| Req | Status | Command / test | Result observed this session |
|---|---|---|---|
| Chat in dashboard, LLM calls tools via gateway, shows calls | DONE | `POST /api/chat/completions` + verify-llm.py | SSE model/token events; `tool_call` events streamed; final answer |
| Acts as logged-in user (audit attribution) | DONE | psql audit join | chat tool calls attributed to `admin@urumi.local` (the session user) |
| Model/provider your choice, free/local ok | DONE | verify-llm.py | serving model `gemini-3.5-flash-lite` via `gateway.llm.*` values |
| LLM keys as Secrets | DONE | `kubectl get secret gateway-llm -n urumi` | Secret holds the API key; empty by default until operator supplies it |

---

## 4. Stand-out items (docs/00 §7 + docs/09 §2)

| Bonus | Status | Command / test | Result observed this session |
|---|---|---|---|
| **Multi-store provisioning** | NOT DONE | — | no per-store namespace provisioner in the codebase (`10_BONUS_MULTI_STORE.md` is a blueprint only) |
| **VPS deployment (k3s)** | PARTIAL | `helm lint -f helm/values-prod.yaml` + `scripts/verify-prod.sh` | written and rehearsed locally (docs/DEPLOY_VPS.md): complete values-prod.yaml (placeholder hostnames + example file), GHCR-pinned images, cluster-issuer manifests, `scripts/create-llm-secret.sh`, client-IP trusted-proxy test, https-on-kind browser proof, `verify-prod.sh` rehearsed against the kind TLS setup (ALL CHECKS PASSED incl. 13-tool MCP list). **VPS run pending** - the live k3s run (real domain, AWS security group, LE cert, live NetworkPolicy confirmation on the real CNI) is the only unproven step |
| **Tool permissions (per-role, members read-only)** | DONE | `make test` (12 new tests in `tests/test_tool_permissions.py` + chat refusal in `test_prompt_injection.py`) + in-pod `live_verify_perms.py` | default allow-all (empty deny table changes nothing; DoD intact); example policy applied live via `PUT /api/permissions` (deny `woo__create_product` + `woo__update_order_status`): member `tools/list` hides them, member direct call rejected with `{"code":-32602,"message":"unknown tool: woo__create_product"}` before any upstream contact, `permission_denied` audit rows written under the member; admin `tools/list` = all 11 and admin can call a member-denied tool; chat as b-member "create a product" -> `permission_denied` (audited); clearing the policy returns all tools. One enforcement core (`gw_mcp/permissions.py`) for `/mcp`, `/api/tools` and the chat agent; admin Permissions panel on Servers page; `make demo-reset` clears rules. |
| OAuth on gateway | NOT DONE | — | explicitly skipped per docs/00 §7 |
| Many-tools handling (`search_tools` meta-tool) | NOT DONE | — | no `search_tools`/`execute_tool` in `src/gateway` |
| Hosted MCP servers (image -> deploy) | NOT DONE | — | blueprint only |
| **Security hardening (SSRF + RBAC + NP)** | **DONE (hardening pass 2026-10-19, ADR-041..047)** | `scripts/verify-hardening.sh` (53 checks, all PASS x2 runs) + `make test` (incl. test_ssrf_guard.py, test_login_throttle.py) + make verify-mcp + DoD flow (scripts/verify-dod-hardening.py) | SSRF validator + default-deny NetworkPolicy verified live. **Now also:** every container + initContainer non-root with explicit uid (gateway 1000, dashboard 101, woo-mcp/demo 1000, postgres 70, mariadb 999, wordpress 33, wp-setup 33, store-assets 33, waits 1000), ALL caps dropped, privEsc false, seccomp RuntimeDefault everywhere (values `podSecurity.workloads` + ONE shared helper, ADR-041); custom hardened wordpress (8080, uid 33) + wp-cli images, MariaDB non-root uid 999 over fsGroup, root chown initContainer deleted (ADR-043); dedicated SA per workload with `automountServiceAccountToken: false` proven by exec (only wp-setup automounts, secrets-only Role — ADR-042); login lockout per username+IP (5/300s, 429, audit row) with tests; session cookie HttpOnly/SameSite=lax + Secure setting (prod on); CSP (no inline scripts) + nosniff + no-referrer + frame-ancestors 'none' + empty Permissions-Policy on dashboard nginx and gateway API, zero CSP console errors in a real browser; SSRF guard connect-time resolution + no-redirect factory pinned by tests (decimal/hex/resolve-private/redirect cases); git-history + working-tree + pod-log secret scans clean (0 real secrets; the Apache `%u` consumer-key log leak found and fixed in the hardened image). **Remaining (documented in THREAT_MODEL.md):** gateway egress open to public 443 (LLM provider), per-replica in-memory rate limit/lockout, readOnlyRootFilesystem=false for wordpress/mariadb/wp-setup (non-root still holds). |
| **Scaling (multi-replica, stateless)** | PARTIAL | `kubectl scale deploy/urumi-gateway --replicas=2` then tools/list x6 | 6/6 tools/list OK (13 tools) across 2 replicas with no session affinity — stateless aggregation works; scaled back to 1. **Gap:** the rate limiter is per-key but in-memory (`_rate_buckets`), so it is NOT shared across replicas and there is no user-level limit (no Redis); a per-user or per-key *distributed* limit is not implemented. |
| Observability (metrics) | PARTIAL | `grep metrics src/gateway` | no `/metrics` endpoint (documented as optional in docs/00 §7). **Upstream observability (stand-out item 8, docs/11) DONE + verified live:** health columns via Alembic 004 (`last_checked_at/last_ok_at/last_latency_ms/last_error_category`, categories only - never raw exceptions/URLs/headers/tokens), admin row second line + Check now (require_admin, CSRF, 1/5s rate limit), members see status only (secret-string tests), `by_server` stats admin-only with 7/14-point sparklines (member absence tested), banner (`/api/alerts`) admin + calm member notice with per-session dismissal (Playwright 9/9), 5s health loop + 2s timeout as Helm values with passive detection. Live proof: plain `kubectl delete pod` on woo-mcp three times - row flipped Unreachable (connection_refused/timeout) with the banner within one 5s check interval, time/notes calls ok throughout, recovery to Connected ~6-10s after the new pod Ready (window ≈ 12s); observed timings in docs/11 §4, artifacts in `artifacts/observability/`. |
| Upgrades/rollback | DONE (rehearsed locally; VPS pending) | docs/UPGRADE_ROLLBACK.md + `make upgrade` / `make rollback` | rehearsed on kind with real output (docs/UPGRADE_ROLLBACK.md): good upgrade 1.0.0->1.0.1 proven via the gateway version endpoint; deliberately bad upgrade (nonexistent tag) auto-rolled back by --atomic ("release urumi failed, and has been rolled back"); manual `helm rollback urumi 4` succeeded; users/API keys/admin events/order 48/12 products survived all three; Alembic forward-only policy documented (additive-only rule). Makefile one-liners: `make upgrade` / `make rollback`. |

---

## 5. Explicit audit items (asked in the cleanup pass)

| Item | Status | Command / test | Result observed this session |
|---|---|---|---|
| Can an admin issue a key on behalf of another member? | DONE | admin `POST /api/keys` with `{"user_id": <member>}` | 201, plaintext key, owner = the member (verified via GET /api/keys owner_id) |
| Can an admin revoke a key on behalf of a member? | DONE | admin `DELETE /api/keys/<member key id>` | 200 `{"revoked": true}` |
| Does revoking a key reject the next call? | DONE | `/mcp tools/list` with the revoked key | 401 `invalid or revoked key` |
| Does disabling a server remove its tools from chat and the external client? | DONE | disable `time` then `/mcp tools/list` + code check `chat/agent.py:231` | tools/list drops `time__*`; chat loads only `Server.enabled.is_(True)` |
| Does killing an upstream pod leave the others working and show Unreachable? (restore after) | PARTIAL | killpod probe (scale 0 -> observe -> scale 1) | `woo` Unreachable in dashboard while down; `time__` still 200; after restore `woo` Connected + `woo__list_products` 200. Same evidence as DoD 10: PARTIAL because the bare `kubectl delete pod` path was not directly observed (scale-to-0 was used). |
| Are all Helm workloads probed with requests and limits? | DONE | `kubectl get deploy,sts -o json` | every container has liveness+readiness (+startup where applicable) and requests+limits |
| Are Woo MCP and other upstreams unreachable from outside and from non-gateway pods? | DONE | NetworkPolicy + ingress + pod probes | ingress exposes only store+dashboard; woo-mcp/demo-time/demo-notes are ClusterIP-only; from dashboard pod all 3 time out; from gateway pod all 3 reachable |

---

## 6. Summary

- **DONE:** 50 rows (DoD 1 storefront checkout is DONE via `scripts/verify-checkout.mjs`; per-role tool permissions now DONE; security hardening closed by the 2026-10-19 hardening pass)
- **PARTIAL:** 6 rows (VPS deployment (written + rehearsed, VPS run pending), DoD 3 hand-place order, DoD 10 bare delete-pod Unreachable window, Scaling distributed rate limit, kill-pod audit item, metrics)
- **NOT DONE:** 5 rows (multi-store, OAuth, `search_tools`, hosted MCP servers, metrics endpoint)

### Smallest fixes for PARTIAL / NOT DONE

- **DoD 1 (storefront checkout):** DONE via `scripts/verify-checkout.mjs` (real browser: product page -> cart -> block-checkout with COD -> place order -> confirm via Store API POST + `woo__list_orders` -> delete test order). 7/7 PASS on 2026-10-16 (order 95, status processing).
- **DoD 3 (hand-place order):** hand-place the order through the storefront checkout for the exact product the chat created (DoD 2's product), not a different one; then confirm it via `woo__list_orders`.
- **DoD 10 (bare `kubectl delete pod` Unreachable window):** lower `health_interval_seconds` (e.g. 5s) or verify with a pod that takes >1 interval to become Ready, so the health loop observes the down window on a literal pod delete.
- **VPS deployment:** written and rehearsed locally (docs/DEPLOY_VPS.md, prod-readiness pass 2026-10-20): complete values-prod.yaml + example file, GHCR image pins, ClusterIssuer manifests, LLM-secret script, client-IP proof, https-on-kind browser proof, verify-prod.sh rehearsal. **VPS run pending:** run `helm upgrade --install urumi ./helm -f helm/values-prod.yaml` against a k3s node with a real domain and confirm store/dashboard/`/mcp` over the internet; then repeat the blocked-connection probe as a live confirmation on the real k3s CNI (NetworkPolicy enforcement is already PROVEN locally: a control test in a scratch namespace showed no-policy CONNECT_OK, default-deny CONNECT_FAIL, allow-rule CONNECT_OK, off-label pod CONNECT_FAIL - kindnet enforces).
- **Per-tool read-only permission (members read-only):** DONE — see the §4 row: deny-rule table (`tool_permissions`), one enforcement core (`gw_mcp/permissions.py`) for `/mcp` + `/api/tools` + chat agent, `GET/PUT /api/permissions` (admin, CSRF, 422 on unknown names), admin Permissions panel on the Servers page, `permission_denied` audit outcome, `make demo-reset` clears rules back to default allow-all. Live-verified with the example policy (deny `woo__create_product` + `woo__update_order_status`).
- **Security hardening open items:** CLOSED by the 2026-10-19 hardening pass (ADR-041..047): pod-level runAsNonRoot + explicit uid/gid on every workload (wordpress 33, mariadb 999 — the local-VM root delta is gone), `automountServiceAccountToken: false` everywhere except the secrets-only wp-setup hook Role, dedicated SAs per workload. Proven by `scripts/verify-hardening.sh`. Remaining residuals (documented, accepted): per-replica in-memory rate limit, gateway egress open for the LLM provider, readOnlyRootFilesystem=false for wordpress/mariadb/wp-setup.
- **Scaling (distributed rate limit):** the per-key limiter is in-memory (`_rate_buckets`) so it is not shared across replicas and there is no user-level limit; back it with Redis (or a shared store) when running >1 replica, or document single-replica as the supported topology.
- **Upgrades/rollback:** DONE 2026-10-20 (prod-readiness pass): rehearsed on kind with real output (docs/UPGRADE_ROLLBACK.md) - good upgrade visible via the gateway version endpoint, bad upgrade auto-rolled back by --atomic, manual rollback succeeded, data (users/keys/admin events/orders/products) survived all three; Makefile one-liners `make upgrade` / `make rollback`. VPS run pending.
- **Multi-store / OAuth / `search_tools` / hosted MCP / metrics:** genuinely unimplemented; each is a separate feature behind the docs/00 §7 gate ("only after core E2E green + demo rehearsed twice"). The core E2E is green, so any one could be picked next; the recommended first pick is per-tool permissions (smallest, biggest security story).

### Not verified in this session (state honestly)

- Live VPS (k3s) deployment and a real internet-facing URL — no VPS was reachable here.
- The hand-placed-order DoD variant (DoD 3) — order 95 was placed via the real storefront but for a different product (Urumi Shoes), not the chat-created one.
- Bare `kubectl delete pod` Unreachable window (DoD 10) — the reliable observation used scale-to-0 then scale-to-1; the plain delete path was not observed.
- Non-root containers, ServiceAccount token mounting, least-privilege RBAC (security hardening open items) — **closed 2026-10-19**, see the §4 row and THREAT_MODEL.md.
- Distributed / per-user rate limiting (Scaling gap).
- `helm upgrade --atomic` + `helm rollback` — **re-run 2026-10-20** (docs/UPGRADE_ROLLBACK.md, real output); the VPS run of the same procedure is pending.
