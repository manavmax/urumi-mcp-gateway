# System Design and Tradeoffs

Required short note. The decision log is in `docs/DECISIONS.md`, the API map in `docs/ENDPOINT_MATRIX.md`, and the VPS walkthrough in `docs/DEPLOY_VPS.md`.

## Architecture

Four layers on Kubernetes (Kind local, k3s VPS) via one Helm umbrella chart (`helm/`), with `values-local.yaml` for kind and `values-prod.yaml` plus a private overlay for the VPS.

- **Store:** WordPress + WooCommerce + MariaDB (StatefulSet + PVCs, Ingress `store.<domain>`), a standalone block theme shipped by a `store-assets` image, and a `wp-setup` Job that provisions WordPress and creates the `woo-secrets` Secret on first install.
- **Woo MCP (custom):** Python FastAPI + the `mcp` SDK over Streamable HTTP, 8 tools (products, orders, product images) via the Woo REST `wc/v3` API with consumer key/secret. ClusterIP only; the NetworkPolicy admits the gateway only.
- **Gateway:** FastAPI. MCP client to N upstreams, MCP server at `POST/GET /mcp`, admin REST `/api/*`, chat agent, stores/hosted sync, OAuth. Aggregates tools under `slug__tool` names, enforces permissions, rate limits, SSRF validation and audit for every call. Credentials Fernet encrypted at rest, never sent to the browser or client.
- **Dashboard:** React + Vite + TS + TanStack Query behind nginx; Servers/Members/Keys/Audit/Chat/Metrics/Stores/Hosted pages. The chat agent runs a server side LLM loop as the logged in user with SSE streaming and tool chips.
- **Extra upstreams:** time and notes demo servers, giving 3 seeded upstreams and 13 aggregated tools (`woo__*` 8, `time` 2, `notes` 3).
- **DB:** PostgreSQL StatefulSet for users, keys, servers, tool cache, audit, permissions, stores/hosted/OAuth tables; async SQLAlchemy + Alembic.

## Aggregation, routing and failure handling

The gateway is a stateless MCP aggregator: one `/mcp` endpoint, tools from all enabled upstreams returned under deterministic `slug__tool` names (e.g. `woo__list_orders`), stateless `JSON-RPC` (no `Mcp-Session-Id`), so replicas scale without Redis.

- **Timeouts (`ADR-089`/091):** the `tools/list` fan out is cut off at `list_timeout_seconds` (3s, Helm `gateway.timeouts.listSeconds`); a `tools/call` without an explicit per server timeout gets `call_timeout_seconds` (15s). Store and hosted internal upstreams follow the same global call timeout. A legacy per server `timeout_ms` of 10000 means "follow the global" (sentinel), explicit values still win.
- **Failure isolation:** per upstream `httpx.Timeout`, `asyncio.gather(return_exceptions)` so a dead upstream never blocks the fan out, and a per server circuit breaker (3 consecutive failures open it, 60s reset with a half open probe) that fails fast while open.
- **Stale cache fallback:** when an upstream is unreachable or its breaker is open, `tools/list` serves the last known tool cache with a `stale_cache` warning instead of lying about connectivity or dropping the server from the list.
- **Health loop:** periodic probes mark each server Connected / Unreachable / Disabled on the dashboard; readiness is derived from real traffic outcomes, not config.
- **Audit:** writes go through an async queue (10k buffer) so logging never blocks the request path; outcomes are classified (success, upstream_error, permission_denied, timeout, circuit_open, validation_error, rate_limited, protocol_error).

Tradeoffs accepted: the 3s list cut off can drop a genuinely slow server's tools for that request; the stale cache fallback means a listed tool can briefly fail when called; fixed 60-second `rate-limit` buckets instead of a sliding window; the breaker and health state are in process, so a gateway restart clears them.

## Stores (`ADR-060`, Phase 5)

A single purpose provisioner Deployment (helm CLI + the store chart baked into its image, its own ServiceAccount, reachable only from gateway pods) turns dashboard actions into `store-<slug>` namespaces via `helm upgrade --install`. The gateway owns the rules (who may create what, caps, slug rules, lifecycle rows); the provisioner owns the cluster calls. Store state is derived from the cluster (WordPress AND `woo-mcp` Deployments Available plus helm release deployed), not task bookkeeping, so a provisioner restart resumes cleanly and "Ready" always means "serving". WooCommerce keys stay in the store namespace; the gateway never sees them. Tool names appear as `<slug>__list_orders` etc. Teardown is a namespace delete behind a DELETING label applied first, so a crash mid teardown resumes deleting. Store state on the VPS: `stores.globalMax=3`, `maxPerUser=1`, `maxConcurrent=1`, per namespace ResourceQuota + LimitRange, and per store TLS via `cert-manager` `HTTP-01` (no wildcard; see THREAT_MODEL).

## Hosted servers (`ADR-062`)

Admins add MCP servers by container image: tag/digest required, `:latest` refused, registry allowlist, no SA token, read only rootfs, gateway only ingress, DNS only egress, env values in a cluster Secret never returned by any API. Hosted tools appear in `/mcp` like any upstream (`<name>__tool`) and are removed completely on delete. Residual risk of arbitrary admin chosen images is stated in THREAT_MODEL.md.

## OAuth (`ADR-063`)

Minimal correct MCP authorization: RFC 9728/8414 metadata, RFC 7591 dynamic registration (public clients, exact match redirects), authorization code + PKCE S256 only, RFC 8707 resource binding, opaque 5-minute access tokens, rotating refresh tokens with family revocation, everything hashed at rest. Tokens map to users with the same permissions, rate limits and audit rows as API keys. The browser part is the dashboard session plus a consent page. API keys keep working alongside.

## Rate limits and compact tool mode (`ADR-057`/058)

Rate counters live in Postgres (atomic upsert), per key plus per user, working across replicas; `over-limit` returns a clear MCP error with `Retry-After`, an audit row and a metric. Compact tool mode is opt in per client (`X-Gateway-Mode: compact`): `tools/list` returns two meta tools and `gateway__call_tool` routes through the same permissions, rate limit, timeout and audit path (the audit shows the real tool name). The chat agent switches automatically above `gateway.compactThreshold`.

## Observability (`ADR-056`)

`prometheus_client` `/metrics` in cluster only (NetworkPolicy, not through Ingress, optional bearer token). Failure reasons are classified on server cards and in audit. The dashboard Metrics page computes per server calls, error rate, p50/p95 and top failure reasons from the audit table, so no Prometheus server needs to run; a real scrape is still available in cluster. Audit table aggregates are eventually consistent (async writer) and bounded by audit retention.

## Production changes (local kind -> VPS k3s)

Same chart; only values change (`helm/values-prod.yaml` placeholders, `helm/values-prod.example.yaml` documents the filled shape; the real domain lives only in an uncommitted overlay, ADR 050).

| delta | local (kind) | prod (k3s VPS) |
|---|---|---|
| DNS / hosts | `*.127.0.0.1.nip.io` + kind extraPortMappings | real domain via private overlay (never committed) |
| Ingress | kind `ingress-nginx` manifest | same chart, `externalTrafficPolicy=Local` for client IP preservation |
| TLS | `cert-manager` SelfSigned for kind tests | `cert-manager` staging issuer first, then production (LE rate limits); ACME solver allow policy (`ADR-051`) |
| Storage class | `standard` | `local-path` (k3s default), PVC sizes from values |
| Images | node local `urumi/*`, pullPolicy Never (ctr import) | `ghcr.io/<owner>/<name>:<appVersion>-<sha>` pinned, IfNotPresent, optional imagePullSecrets |
| Secrets | chart generated, lookup guarded | unchanged + `existingSecret` options; LLM key via hidden prompt script |
| Replicas | 1 | 1 (single PVCs for stateful parts; in memory lockout is per replica, documented) |
| Trusted proxies | ingress pod IP | k3s pod CIDR so forwarded `X-Forwarded-For` survives (in cluster spoofing documented, `ADR-049`) |
| Storage/requests | chart defaults | CPU requests lowered to fit the 2 vCPU node (700m total), limits untouched |

Deployed for real on 2026-10-20 (k3s on a VPS, Let's Encrypt production cert). The first live run found four gaps, each now fixed and documented in `docs/DEPLOY_VPS.md`: fresh installs must run without `--wait` (the `wp-setup` hook creates the Secret `woo-mcp` waits for; helm only runs hooks after `--wait`), a 2 vCPU node needs a request budget counted against system pods (requests lowered, limits untouched), the default deny policy must explicitly admit `cert-manager`'s ACME solver pods (`ADR-051`, now values driven), and ACME has transient server side failures (delete the failed CertificateRequest, `cert-manager` retries).

## Helm upgrade and rollback

Rehearsed procedure with real output in `docs/UPGRADE_ROLLBACK.md`; the short story:

- First install on a fresh cluster runs WITHOUT `--wait` (the `wp-setup` hook creates the Secret that `woo-mcp` needs to become Ready; helm runs hooks only after `--wait` is satisfied, so `--wait` on a fresh install deadlocks). Wait with `kubectl wait --for=condition=complete job/urumi-wp-setup`. `make helm-prod-first` covers it.
- Every later upgrade: `helm upgrade --install ... --timeout 15m --rollback-on-failure --wait` (helm 4 spelling of atomic; the Makefile auto detects the helm major version). A failed upgrade rolls back automatically; rehearsed with a deliberately bad upgrade.
- Take a `pg_dump` before upgrading; the restore drill was executed for real (dump copied off the pod, restored into a scratch DB, alembic_version and row counts verified, then a real restore into the live DB with the gateway scaled down).
- The honest limit: **a rollback via helm after a forward only migration is refused by the schema gate.** The gateway runs `alembic upgrade head` on start and then reads `alembic_version` through a separate connection, comparing it with the alembic head the code ships with. Roll the code back across a migration boundary and the database is ahead of the code: the new (old) gateway logs a clear ERROR, `/readyz` goes unready, and the process exits 3 by design. Recovery is the pre upgrade pg_dump restore, or reapplying the newer release. Code from before the gate existed still runs against a newer schema (every migration so far is additive), but the gate exists precisely to stop silent forward only drift being papered over by a helm rollback.

## Security controls and accepted tradeoffs

The control table (non root uids, SAs, default deny NetworkPolicies, lockout, cookies, CSP, SSRF, secret hygiene) lives in THREAT_MODEL.md with its proof scripts (`scripts/verify-hardening.sh`, 64 checks against the live cluster). Accepted tradeoffs: public 443 egress for the LLM, provider visible chat content, per replica counters, three readOnlyRootFilesystem exceptions, the provisioner ClusterRole, admin chosen hosted images, and (prod) trusting the k3s pod CIDR for `X-Forwarded-For`, which only `ingress-nginx` can exploit because the chart's NetworkPolicy admits only the controller.

## Stand out

VPS deploy rehearsed then real; per tool RBAC with audited denials; stores provisioner with per store namespaces and TLS; hosted servers with a registry allowlist; OAuth for MCP clients; audit derived metrics page; optional `search_tools` meta tool and compact mode for many server scale.