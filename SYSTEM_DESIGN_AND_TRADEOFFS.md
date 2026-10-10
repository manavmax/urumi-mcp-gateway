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

## Production Deltas (local → VPS)

Only `values-*.yaml` changes — same chart: `domain` (nip.io → real), `storageClass` (standard → local-path/longhorn), `ingressClass`/`tlsEnabled` + cert-manager `ClusterIssuer`, `resources`/`replicas` (gateway 1→2), secrets via `kubectl create secret` (no hardcode). Ingress hosts `store.<domain>` + `dashboard.<domain>` (paths `/api`, `/mcp` → gateway). Upgrade `helm upgrade --install --atomic`; rollback `helm rollback`.

## Failure Handling

Timeout 10s per call, health probe 15s, breaker open 30s, audit async queue (10k) never blocks request, `follow_redirects=False` + DNS IP blocklist.

## Stand-out

VPS deploy, per-tool RBAC (members read-only), deny-by-default NetworkPolicy + SSRF validator, optional `search_tools` meta-tool for many-server scale.
