# System Design and Tradeoffs

## Architecture

Four layers on Kubernetes (Kind local, k3s VPS) via one Helm umbrella chart (`helm/`) with `values-local.yaml` vs `values-prod.yaml` diff.

- **Store:** WordPress + WooCommerce + MariaDB (StatefulSet + PVCs, Ingress `store.<domain>`).
- **Woo MCP (custom):** Python FastAPI + `mcp` SDK Streamable HTTP, 6 tools (`list_products`, `get_product`, `create_product`, `list_orders`, `get_order`, `update_order_status`) via Woo REST `wc/v3` + CK/CS (ClusterIP-only, caller: gateway via NetworkPolicy).
- **Gateway:** FastAPI — MCP client to N upstreams + MCP server at `POST/GET /mcp` + admin REST `/api/*` + chat. Aggregates with `slug__tool` prefix, fan-out via `asyncio.gather(return_exceptions)+wait_for(8s)`, per-server `httpx.Timeout` + circuit breaker. Health loop marks Connected/Unreachable/Disabled. Credentials Fernet-encrypted, never to browser/client.
- **Dashboard:** React+Vite+TS+TQ — Servers/Members/Keys/Audit/Chat. Chat server-side LLM loop (OpenAI gpt-4o-mini, swappable) acts as logged-in user; SSE streams tokens+tool chips; audit attributed to real user.
- **Extra upstreams (3 total):** woo-mcp + time + memory — proves cross-server `tools/list` and one prompt needing 2 servers.
- **DB:** PostgreSQL (StatefulSet) for users/keys/servers/tools/audit/permissions; async SQLAlchemy + Alembic.

See `docs/01_ARCHITECTURE.md` for diagrams and request flows.

## Key Decisions

| Decision | Choice | Tradeoff |
|---|---|---|
| Woo integration | REST `wc/v3` + CK/CS | Preserves hooks, no pod exec; WP-CLI only for seeding Job. Direct DB would bypass Woo. |
| MCP transport | Streamable HTTP (2025-03-26) | Single endpoint, Ingress-friendly; stateless gateway (no `Mcp-Session-Id`) scales to N replicas without Redis, but no SSE resume. |
| Aggregation collision | Prefix `slug__tool` (e.g. `woo__list_products`) | Deterministic, spec-compliant uniqueness, LLM-friendly; longer names vs wrapper object that breaks spec. |
| Failure isolation | `httpx.Timeout` + `wait_for` + `gather(return_exceptions)` + breaker + health loop | Dead upstream never blocks others; stale cache 30s; breaker fails fast. |
| Auth domains | Gateway keys (argon2id+sha lookup) ≠ upstream creds (Fernet encrypted) | Upstream never sees user keys; compromise isolation; extra crypto code. |
| DB | Postgres over SQLite | Concurrent audit writes + multi-replica safe + partitioning; heavier than SQLite single-file. |
| LLM | `gpt-4o-mini` swappable to Anthropic/Ollama | Cheap tool calling; abstract provider so free/local fallback is one env var. |
| Storefront | Standalone block theme + store-assets image + by-SKU seeding (ADR-037..040) | Zero third-party requests (self-hosted fonts, hooks removed) and a values-driven image/initContainer copy survive PVC reuse; seeding protects admin edits unless `seedForce=1`; block cart/checkout kept and restyled so no field is hidden or reordered and COD stays default. |

## Production Deltas (local → VPS)

Only `values-*.yaml` changes — same chart: `domain` (nip.io → real), `storageClass` (standard → local-path/longhorn), `ingressClass`/`tlsEnabled` + cert-manager `ClusterIssuer`, `resources`/`replicas` (gateway 1→2), secrets via `kubectl create secret` (no hardcode). Ingress hosts `store.<domain>` + `dashboard.<domain>` (paths `/api`, `/mcp` → gateway). Upgrade `helm upgrade --install --atomic`; rollback `helm rollback`.

## Failure Handling

Timeout 10s per call, health probe 15s, breaker open 30s, audit async queue (10k) never blocks request, `follow_redirects=False` + DNS IP blocklist.

## Security Controls (hardening pass 2026-10-19, ADR-041..047)

| Control | Where | Proof |
|---|---|---|
| Non-root + explicit uid, ALL caps dropped, no privEsc, seccomp RuntimeDefault | every container + initContainer (gateway 1000, dashboard 101, woo-mcp/demo 1000, postgres 70, mariadb 999, wordpress 33, wp-setup 33, store-assets 33, waits 1000) | `scripts/verify-hardening.sh` §1 (kubectl exec id per pod) |
| `readOnlyRootFilesystem` | true: gateway, dashboard, woo-mcp, demo-*, postgres (emptyDirs for /tmp + sockets); false (documented): wordpress, mariadb, wp-setup | verify-hardening.sh table |
| PVC group-write without root | pod fsGroup (70/999/33) replaces the root chown initContainer | helm/templates + live uids |
| Dedicated ServiceAccounts, no token automount | 8 workloads automount=false; only wp-setup automounts (secrets-only Role) | exec: no token dir on all 8 workloads |
| Default-deny NetworkPolicy + values-driven allows | throwaway pod blocked from woo-mcp/notes/time/postgres/mariadb; gateway reaches all 4 upstreams; gateway egress public-443-only (LLM) | verify-hardening.sh §2 |
| Login lockout (username + IP) | 5 fails/300s → 429 generic text + one audit row; in-memory, per replica | verify-hardening.sh §3 + test_login_throttle.py |
| Session cookie | HttpOnly, SameSite=lax, Secure via `gateway.sessionCookieSecure` (prod ON) | live Set-Cookie probe |
| Security headers + CSP | dashboard nginx + gateway API: CSP self-only, no inline scripts, frame-ancestors 'none', nosniff, no-referrer, empty Permissions-Policy | verify-hardening.sh §4 + zero CSP console errors in a real browser |
| SSRF guard | save-time shape + connect-time DNS re-resolution, decimal/hex/metadata/redirect cases pinned by tests; one shared `follow_redirects=False` client factory | `src/gateway/tests/test_ssrf_guard.py` |
| No secrets in git/values/logs | generated Secrets (or operator-provided), placeholder values files, log scans 0 key-shaped strings (the Apache `%u` consumer-key leak found and fixed) | working-tree + git-history blob scan + verify-hardening.sh §5 |

Trade-offs accepted: gateway egress open to public 443 (LLM provider IP unknowable); the LLM provider sees chat text and images; per-replica in-memory rate limit/lockout (single-replica demo); readOnlyRootFilesystem=false for wordpress/mariadb/wp-setup (non-root still holds); wp-setup is the only token-mounted SA (secrets-only Role, ~2 min lifetime per hook run).

Trade-offs accepted: gateway egress open to public 443 (LLM provider IP unknowable); the LLM provider sees chat text and images; per-replica in-memory rate limit/lockout (single-replica demo); readOnlyRootFilesystem=false for wordpress/mariadb/wp-setup (non-root still holds); wp-setup is the only token-mounted SA (secrets-only Role, ~2 min lifetime per hook run).

## Stand-out

VPS deploy, per-tool RBAC (members read-only), deny-by-default NetworkPolicy + SSRF validator, optional `search_tools` meta-tool for many-server scale.

## API map

Every dashboard tile/card and its live endpoint. "Admin" scope means the member
response is scoped to the signed-in user (server-side); "Member" rows are the
own-account values shown to a non-admin.

| Page | Tile or card | Endpoint | Role scope |
|---|---|---|---|
| Overview (admin) | Fleet health subtitle, tool-call volume, success rate, p95 latency, per-day chart, delta vs previous window | `GET /api/stats?range=` | Admin sees all users; member sees own rows |
| Overview (admin) | Servers connected / unreachable / disabled | `GET /api/servers` | Read-only, both roles |
| Overview (admin) | My account (name, role, active keys) | `GET /api/me` + `GET /api/keys` | Own account only |
| Overview (admin) | Recent activity (latest 8 calls) | `GET /api/audit?limit=8` | Admin sees all; member sees own rows |
| Overview (admin) | Tools overview (exposed tools by server) | `GET /api/tools` | Read-only, both roles |
| Overview (member) | My calls / success rate / p95 / per-day chart | `GET /api/stats?range=` (member branch: `own_calls_total`, `own_api_key_calls`, `own_keys_active`) | Own account only |
| Overview (member) | Servers connected (permissioned read) | `GET /api/servers` | Read-only, both roles |
| Overview (member) | Recent activity | `GET /api/audit?limit=8` | Own rows only |
| Overview (member) | Tools I can use | `GET /api/tools` | Read-only, both roles |
| Overview (member) | Getting-started steps (create key, connect client, first call) | `GET /api/stats` (own counters) + `GET /api/keys` | Own account only |
| Servers | Registered / connected / unreachable / unknown / disabled summary | `GET /api/servers` | Read-only, both roles |
| Servers | All servers table (status, enabled, tools) | `GET /api/servers` + `GET /api/tools` | Read-only; admin CRUD via `POST/PATCH/DELETE /api/servers` + `POST /api/servers/{id}/enable|disable` |
| Members | Members / active accounts summary (admin) | `GET /api/users` | Admin only (403 for member) |
| Members | Your role (member) | `GET /api/me` | Own account only |
| Members | API keys summary + keys table | `GET /api/keys` | Admin sees all keys; member sees own |
| Members | Key storage note (SHA-256, shown once) | `GET /api/keys` | Both roles |
| Members | Invite member form | `POST /api/users` | Admin only |
| Members | Delete member row | `DELETE /api/users/{id}` | Admin only |
| Members | Revoke key row | `POST /api/keys/{id}/revoke` | Own keys (member) or any (admin) |
| Members | New-key reveal card | `POST /api/keys` | Own account (member) or on behalf (admin) |
| Audit | Scoping banner, filter form, table | `GET /api/audit` | Admin sees all + user filter; member own rows only |
| Audit | CSV export | `GET /api/audit/export` | Admin only, capped 5000 rows |
| Chat | Thread, SSE tokens + tool chips, model badge | `POST /api/chat` (SSE) | Both roles; member acts as themselves |
| Chat | History search | Client-side filter over the loaded thread history | — |
| Topbar | Signed-in user + role | `GET /api/me` | Own account only |
| Sidebar/Overview | Page search | Client-side filter of the current page (no endpoint) | — |

