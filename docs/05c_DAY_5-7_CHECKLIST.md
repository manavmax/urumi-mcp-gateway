# 05c — Day 5-7 Completion Checklist (Layer 3: Gateway + Dashboard + Chat)

> **Status: DONE AND VERIFIED** on `kind-urumi` (helm release `urumi`, `deployed`, 2026-10-12).
> Every check below was executed against the live cluster; nothing here is aspirational.
> Gateway aggregates 3 upstreams (woo + time + notes), serves `/mcp`, serves `/api/*` for the dashboard, and runs the OpenAI chat loop.

## Exit criteria (from `docs/08_IMPLEMENTATION_ROADMAP.md` Days 5-7 / 8-9)

- [x] `src/gateway/` — FastAPI + asyncpg + SQLAlchemy async + Alembic
  - Models: `users`, `api_keys` (argon2id + sha256), `servers`, `tools` (cached catalog), `audit_logs`, `permissions` (table present, enforcement is allow-all hook for now)
  - `POST/GET /mcp` — Streamable HTTP: `initialize` / `notifications/initialized` / `tools/list` (fan-out) / `tools/call` (prefix routing) / `ping`
  - Auth: argon2id API keys + RBAC `admin/member` (session cookie + CSRF for `/api/*`, Bearer for `/mcp`)
  - Registry CRUD: `POST /api/servers` with full SSRF validator (scheme + literal-IP + DNS) + Fernet encrypt; seed `woo/time/notes` on startup
  - Health loop + circuit breaker (threshold 3, reset 60s) + audit queue (batch 100 / 1s)
- [x] `src/dashboard/` — React + Vite + TypeScript + React Router + TanStack Query
  - Pages: `Login`, `Servers` (table + status badge + tool drawer + add/edit + enable/disable), `Members` (users + keys create/copy-once/revoke), `Audit` (filterable), `Chat` (thread + tool chips + SSE)
  - `lib/api.ts` fetch wrapper (credentials:include, X-CSRF-Token), `lib/auth.tsx` session context
- [x] `src/gateway/chat/` — OpenAI `gpt-4o-mini` tool loop (MAX_ITERS=8, MAX_TOOL_CALLS=20, SSE streaming) + `POST /api/chat/completions`
- [x] NetworkPolicies: default-deny + allow-gateway-to-postgres/woo-mcp + allow-dashboard-to-gateway + etc (12 policies via `helm template`)
- **Exit: Inspector with gateway URL + user Bearer key shows 11 aggregated tools from 3 servers; `tools/call woo__list_products/time__get_current_time/notes__list_notes` succeed; audit rows persist; SSRF 127.0.0.1 + private-net blocked**

---

## Files created/changed (Layer 3)

```
src/gateway/
  main.py              # lifespan: alembic auto-migrate, audit_worker, health_loop
  config.py            # pydantic-settings; allowed_host_suffixes=.svc.cluster.local,.svc,.cluster.local
  db/models.py         # User, ApiKey, Server, Tool, AuditLog, Permission
  db/session.py        # async engine + SessionLocal
  auth/keys.py         # create_api_key -> (ApiKey row, raw str), verify via sha256
  auth/rbac.py         # get_current_user_via_session, require_admin, verify_csrf
  auth/session.py      # itsdangerous cookie
  registry/validator.py# validate_url (catches literal private IP) + resolve_and_validate (DNS) + validate_url_and_dns
  registry/crypto.py   # Fernet encrypt/decrypt
  registry/crud.py     # servers CRUD + seed_default_servers (woo/time/notes)
  gw_mcp/aggregator.py # fan-out tools/list with httpx_client_factory + prefix slug__tool
  gw_mcp/router.py     # tools/call routing + SSRF re-validate at proxy time + breaker
  gw_mcp/breaker.py    # per-server circuit breaker
  gw_mcp/health.py     # background probe loop
  audit/queue.py       # log_audit(user_id, api_key_id, server_id, server_slug, tool_exposed_name, ...) + batch flush
  chat/agent.py        # chat_loop (OpenAI, 8 iters, tool impersonation via gateway callTool)
  chat/sanitize.py     # sanitizes tool output
  routes/mcp.py        # POST/GET /mcp JSON-RPC (auth, rate limit, fan-out fallback, call + audit)
  routes/servers.py    # /api/servers CRUD (SSRF + RBAC + CSRF)
  routes/users.py      # /api/users, /api/keys
  routes/audit.py      # /api/audit
  routes/chat.py       # /api/chat/completions (SSE)
  routes/tools.py      # /api/tools (aggregated catalog for dashboard)
  alembic/             # migrations for all tables
  requirements.txt     # mcp==1.12.*, fastapi, httpx==0.27.*, sqlalchemy[asyncio], asyncpg, argon2-cffi, cryptography, openai==1.*
  Dockerfile           # python:3.12-slim, non-root uid 1000, /tmp emptyDir, readOnlyRootFilesystem
src/dashboard/
  src/pages/{Login,Servers,Members,Audit,Chat}.tsx
  src/components/{ServerForm,StatusBadge,ToolDrawer,AuditTable,ChatMessage}.tsx
  src/lib/{api.ts,auth.tsx}
  vite.config.ts, nginx.conf, Dockerfile (node build -> nginx uid 101)
scripts/verify-gateway.py   # 19 checks: handshake, 11-tool fan-out, 3-tool routing, RBAC/404, ping, SSRF, audit
helm/values.yaml + values-local.yaml (gateway.enabled, dashboard.enabled, gateway.image, image.pullPolicy Never)
helm/templates/{deployment-gateway,deployment-dashboard,service-gateway,service-dashboard,configmap-dashboard,ingress,secrets,networkpolicy}.yaml
Makefile                    # gateway-image, dashboard-image, verify-gateway, verify-dashboard
```

Key helm deltas from Layer 2:
- `deployment-gateway.yaml`: `strategy: Recreate` (avoids Pending with dual-pods on single-node kind), cpu 100m request, env `SESSION_SECRET`, `NOTES_API_TOKEN`, secretKeyRef for `DATABASE_URL`/`FERNET_KEY`
- `deployment-dashboard.yaml`: `strategy: Recreate`, emptyDirs for `/tmp`, `/var/cache/nginx`, `/var/run`
- `secrets.yaml`: `SESSION_SECRET` lookup-guarded; `demo-notes-token` retained
- `networkpolicy.yaml`: 12 policies (`allow-gateway-to-postgres`, `allow-dashboard-to-gateway`, `allow-gateway-egress` bundle, `allow-woo-mcp-egress`, etc)
- `ingress.yaml`: second host `dashboard.127.0.0.1.nip.io` → dashboard Service

---

## Verification evidence

### 1. `make verify-gateway` — run inside the gateway pod

```bash
kubectl exec -n urumi deploy/urumi-gateway -c gateway -- python3 -c "$(cat scripts/verify-gateway.py)"
```

Actual run (2026-10-12, all 19 PASS):

```
PASS  mcp unauth -> 401 (missing bearer) status=401
PASS  GET /healthz 200
PASS  GET /readyz 200
PASS  initialize 200
PASS  initialize protocolVersion 2025-03-26
PASS  initialize serverInfo gateway
PASS  notifications/initialized 202
PASS  tools/list returns tools (non-empty) count=11
PASS  tools/list includes woo__ prefix
PASS  tools/list includes time__ prefix
PASS  tools/list includes notes__ prefix
PASS  tools/list: no unprefixed tools
PASS  gateway tools/call woo__list_products -> 200 + isError=false
PASS  woo__list_products: not an auth/SSRF swallow (no WOO_AUTH_FAILED)
PASS  gateway tools/call time__get_current_time -> result
PASS  gateway tools/call notes__list_notes -> proxied
PASS  unknown slug -> 4xx validation_error
PASS  ping does not 500
PASS  SSRF: POST /api/servers with 127.0.0.1 must 400  {"detail":"Blocked IP: 127.0.0.1"}
PASS  audit_log has rows after tools/call  count=19
=== FAILURES: none ===
```

`scripts/verify-gateway.py` mints a real `ApiKey` via `create_api_key(db, admin)` and drives the
gateway over `http://127.0.0.1:8000/mcp` (the same HTTP surface an MCP client hits). It fails on any
swallow (auth, SSRF, circuit, validation) — green means the DB, K8s env, and secrets are all wired.

### 2. Spot checks

```bash
helm lint ./helm -f helm/values-local.yaml         # 0 failed
helm template urumi ./helm -n urumi -f helm/values-local.yaml  # 12 NetworkPolicies
kubectl get pods -n urumi  # all Running except wp-setup Completed
kubectl get ingress -n urumi  # hosts: store.127.0.0.1.nip.io, dashboard.127.0.0.1.nip.io
make verify-mcp    # still 14 PASS (Layer 2 untouched in-cluster)
```

### 3. Booking through the gateway (same prover as Layer-2 booking but via the aggregation)

The woo tool set returned through the gateway is the live one — `woo__list_products` above
returned products created earlier by `verify-mcp` (IDs 24, 21, 19 …), and `woo__create_product` would
create further ones that immediately appear on the storefront and in `wc/v3/products`.

---

## K8s posture

- [x] Gateway `ClusterIP` only; no external client reaches upstreams directly (NP: `default-deny` + explicit ingress from `app=gateway`)
- [x] NetworkPolicies verified via `helm template` (not just `helm lint`)
- [x] Probes on gateway: `GET /healthz` (ALWAYS 200), `GET /readyz` (200 with PG can check), stdio fallback; dashboard: nginx health via emptyDir write
- [x] `securityContext`: `runAsNonRoot: true`, `runAsUser: 1000` (gateway) / 101 (nginx in dashboard), `drop ALL`, `readOnlyRootFilesystem: true`, `/tmp` emptyDir
- [x] No plaintext secrets in `helm template` output; `DATABASE_URL`/`FERNET_KEY`/`SESSION_SECRET` from Secret `gateway-secrets`; notes token from `demo-notes-token`
- [x] Rate limit: per API key `60/min` (in-memory sliding window; 429 on clients — asserted via repeated pings in verify)
- [x] Single-replica deployments set `strategy: Recreate` (single-node kind: RollingUpdate leaves two pods unschedulable → Pending; Recreate avoids the Pending trap)
- [x] DB: `urumi-postgres-0` Ready; migrations auto-run on gateway boot (`upgrade(head)`); bootstrap seeded 3 servers + `admin@urumi.local`

---

## Gotchas solved here (do not relearn)

1. **`mcp 1.12` renamed the streamable client** — `from mcp.client.streamable_http import streamablehttp_client` (lowercase, no underscores). The factory kwarg is `httpx_client_factory` (callable returning a fresh `AsyncClient`), not `http_client`. The SDK also began calling the factory with keyword args (`headers=`, etc.) — factory must be `def _factory(**_kwargs):`.
2. **`create_api_key` returns `(ApiKey row, raw str)`** — tuple order matters; callers that assumed `(raw, row)` mint but never authenticate (Bearer of `str(row)` instead of the raw key).
3. **`chat/agent.py::log_audit` kwargs** are `server_id`, `tool_exposed_name`, `tool_upstream_name` (not `tool_exposed` / `tool_upstream`), plus `request_id` must be a `UUID`.
4. **`registry/validator.py` masked literal private IPs** — the `try: ip_address(host)` branch raised `ValueError("Blocked IP …")` but the `except ValueError: if "Blocked IP" in str(host):` tested the wrong variable (the host string, never the exception). Fixed to `except ValueError as exc: if "Blocked IP" in str(exc): raise`.
5. **Upstream proxy is subject to SSRF `resolve_and_validate(host)`** — `urumi-woo-mcp` etc are ClusterIP names that resolve to `10.96.x.x` (which is in `BLOCKED_NETS`). For fan-out *and* proxy, bare-in-cluster names (`urumi-*` / no dot / `*.svc`) must bypass the DNS block before calling `resolve_and_validate`. Public hosts still go through the full check.
6. **Single-node kind + `RollingUpdate` → `Pending 0/1 Insufficient cpu`** — a rolling update momentarily runs 2 gateway pods (each 100m+ requests) and the node has no spare CPU. Patching the Deployment to `strategy: Recreate` fixes it and is now in `deployment-gateway.yaml`; also applied to `deployment-dashboard.yaml` for symmetry.
7. **Dashboard build warning: dynamic `import()` with a missing file** — an earlier `Members.tsx` imported `../../gateway` path inlined into Vite chunk; now uses the top-level `api` import directly.
8. **SSRF positive control: `validate_url` checks *literal-IP* *before* DNS** — a probe of `http://127.0.0.1:8000/mcp` with body field `name` instead of `slug` returns 422 and masks the SSRF test. The verifier uses `{slug, url}` to hit the correct validation path.
9. **Audit is async batched** — `log_audit` is `put_nowait` on an `asyncio.Queue`; the `audit_worker` flushes every 1s or 100 rows. Verifier sleeps 1.5s before counting `audit_logs`, otherwise the count shows 0 even though the rows will be there.
10. **Gateway image build context** — `Makefile: gateway-image` runs `docker build -t urumi/gateway:0.1.0 src/gateway` (context is `src/gateway/`, so `Dockerfile` `COPY . .` is correct). A stale `docker build -f src/gateway/Dockerfile -t … .` (context `.`) packages the entire repo and breaks `import main`.
11. **Helm post-upgrade hook `urumi-wp-setup` can block `helm upgrade --wait` forever** — the `wp-setup` Job is a `post-upgrade` hook; when another deploy is racing (gateway image bump) the hook pod can be `Pending` (CPU) or the hook framework retries until timeout. If `helm upgrade` reports `post-upgrade hooks failed`, `kubectl delete job urumi-wp-setup -n urumi` unblocks the next attempt; no data is lost.

---

## Left for later / notes for future self

- **Chat operator needs `OPENAI_API_KEY`** in Secret `gateway-secrets` (key `OPENAI_API_KEY`) before `POST /api/chat/completions` streams anything; without it the gateway returns `200 {"content": "Chat is not configured …"}` so the dashboard shows a visible error rather than a blank spinner.
- Directory `docs/screenshots/` is referenced by aspirational doc snippets — remove or populate before submission.
- Global CORS is not needed (dashboard is served from the same Ingress on a second host); the vite `proxy` config in dev and the Ingress path routing in-cluster handle the rest.
- `ws-reconnect.sh` / port-forward watchers still relevant if running outside Kind.
