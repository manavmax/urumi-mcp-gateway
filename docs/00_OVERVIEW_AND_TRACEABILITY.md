# 00 — Overview & Requirement Traceability Matrix

> **Purpose:** Single source of truth for what Urumi grades. Every mandatory line maps to a design decision later.

## 1. The Brief in One Paragraph

Build a **WooCommerce hosting + Team MCP Gateway** on **Kubernetes + Helm**. One Woo store runs in-cluster. A custom MCP server exposes its products/orders. A gateway aggregates N MCP servers behind **one Streamable-HTTP endpoint**; a React dashboard lets admins manage servers/members and members use a chat agent — all tools flow through the gateway, no bypass. Demo must work with **2 users, 2 external surfaces (chat + MCP client), revocation, disable, kill-pod isolation, audit log**.

---

## 2. Scoring Mental Model (how reviewers think)

| Weight | Area | What wins |
|---|---|---|
| 35% | **Working Core E2E** | Demo script passes without hand-waving. Deterministic, testable. |
| 20% | **Kubernetes Correctness** | Helm is clean, values-local vs prod is real diff, probes/resources/Secrets/NetworkPolicy correct. |
| 15% | **MCP Internals Depth** | Can whiteboard: JSON-RPC framing, Streamable HTTP session, aggregation, collision, timeout. |
| 15% | **Security Posture** | Knew where credentials live, hashed keys, SSRF block, no leak to browser/client, NetworkPolicy. |
| 10% | **Chat Agent Loop** | Tool loop works, acts as user, shows tool calls, audit correct. |
| 5% | **Polish (bonus cherry-picked)** | 1-2 stand-out items done *deeply* > 5 done thinly. |

**Rule: working core > unfinished bonus.** Every doc after this enforces that.

---

## 3. Four-Layer System (from brief)

```
Layer 1: Store         — WordPress + WooCommerce + MySQL/MariaDB (PVC, Ingress)
Layer 2: Woo MCP       — Custom Python MCP server (Streamable HTTP, 5 tools)
Layer 3: Gateway+Dash  — FastAPI gateway (MCP client to N upstreams + MCP server at /mcp) + React dashboard
Layer 4: Chat Agent    — LLM tool loop via gateway, acting as logged-in user
```

**Invariant:** `Browser / MCP client -> Gateway /mcp -> Upstream MCP servers`. Nothing else calls upstreams.

---

## 4. User Stories -> Acceptance Tests

### Admin
| US | Test |
|---|---|
| See servers + status + tools | Dashboard lists 3+ servers, each badge: Connected/Unreachable/Disabled, expandable tool list |
| Woo MCP pre-registered | On fresh install, Woo server already present (seeded via Helm Job/ConfigMap) |
| Add/edit/disable/remove server | Form: URL + credential (bearer/header) + slug; edit credential (re-entry required); disable hides tools; remove deletes row + cached tools |
| Invite members + issue/revoke keys | Admin creates member accounts, keys table: create shows plaintext once, revoke sets `revoked_at` -> next call 401 |
| Audit log | Table: who, server, tool, when, duration, outcome (success/error/timeout); filterable |

### Member
| US | Test |
|---|---|
| Generate own API key | Member settings page: Generate -> copy once |
| Single gateway URL + key in MCP client | Claude Code / Cursor / MCP Inspector config: `{ "mcpServers": { "urumi": { "url": "https://dash.../mcp", "headers": {"Authorization":"Bearer <key>"}}}}` -> tools appear |
| Chat via dashboard | Chat input -> LLM calls tools -> answer + tool-call chips |
| Never sees upstream creds | Network tab: no credential in responses; `GET /servers` masks credential; DB encrypted |

---

## 5. Definition of Done — Demo Script (must rehearse)

### Phase A — Store
1. Open `https://store.localtest.me` -> add product to cart -> checkout COD -> see order in `WP Admin > WooCommerce > Orders`.

### Phase B — Chat as User A (admin or member)
2. Chat: "Create a product named 'Urumi Tee' price $29.99" -> verify on storefront.
3. Hand-place order for that product on storefront.
4. Chat: "What orders came in today?" -> agent returns that order (proves `list_orders` with date filter).

### Phase C — External MCP Client as User B (different key/role)
5. Connect Inspector/Claude Code with `gateway URL + User B key` only -> `tools/list` returns all enabled servers' tools.
6. Ask same orders question -> succeeds.
7. One prompt needing 2 servers: e.g. "Create a product and also search Notion/GitHub for 'Urumi' " -> shows cross-server aggregation.

### Phase D — Control Plane
8. Revoke User B key -> next `tools/call` -> `401 Unauthorized`.
9. Disable one upstream (e.g. second server) -> its tools vanish from chat + client `tools/list`.
10. `kubectl delete pod <woo-mcp-pod>` -> other servers still respond; dashboard shows Woo as Unreachable (health loop).
11. Audit log shows every call above with correct user attribution.

**Rehearsal tip:** Record in one take, no cuts. Pre-seed store with 2 products for speed, but the live `create_product` must be visible.

---

## 6. Mandatory Requirements Traceability

### 6.1 Kubernetes & Helm
| Req | Design Answer | Where Documented |
|---|---|---|
| Local Kind/k3d/minikube + VPS k3s same charts, values diff only | Umbrella Helm chart with `values-local.yaml` (standard/local-path, nip.io, no TLS) vs `values-prod.yaml` (longhorn/ebs, real domain, TLS) | `06_KUBERNETES_AND_HELM.md` |
| Helm mandatory, no Kustomize | `helm/` chart + `helm upgrade --install urumi ./helm -f values-local.yaml` | 06 |
| Everything in-cluster (store, DB, woo-mcp, gateway, dashboard) | 5 Deployments/StatefulSets in `urumi` namespace (bonus: per-store namespaces) | 01, 06 |
| PVC for DB + wp-content | `PVC wp-data 10Gi RWO`, `PVC wp-content 5Gi RWO`, `StorageClass` parametrized | 06 |
| Ingress with stable URLs, document local domain | `Ingress` 2 hosts: `store.<domain>` + `dashboard.<domain>`, local via `*.127.0.0.1.nip.io` or `/etc/hosts` + Kind `extraPortMappings` | 06 |
| Readiness/liveness (+ startup) + requests/limits | Every workload has probes + `requests/limits`; WordPress startupProbe 150s | 06 |
| No hardcoded secrets, use K8s Secrets | `Secret gateway-secrets`, `Secret woo-secrets`, `Secret mariadb-secret` + `lookup` in templates, `.gitignore .env` | 06, 07 |

### 6.2 WooCommerce MCP Server
| Req | Answer |
|---|---|
| Write yourself, no existing server | Python FastAPI + `mcp` SDK, custom tools |
| Streamable HTTP | `StreamableHTTPSessionManager` at `/mcp`, JSON + SSE support |
| Tools: list_products, create_product, list_orders, get_order, update_order_status | 5 tools + optional `get_product` bonus | 
| Not reachable outside cluster | `ClusterIP` Service, `NetworkPolicy` allow only `gateway` -> `woo-mcp:8000`, no Ingress |
| Doc how it talks to store | Woo REST API `wc/v3` with Consumer Key/Secret via `httpx`; rationale vs WP-CLI/DB | `03_WOOCOMMERCE_MCP_SERVER.md` |

### 6.3 Gateway
| Req | Answer |
|---|---|
| Add/edit/disable/remove upstreams (Streamable HTTP + static cred) | `servers` table + admin REST CRUD, `auth_type: bearer/header` |
| One MCP endpoint aggregating tools, routing calls | `POST /mcp` + `GET /mcp` (SSE), prefix `slug__tool` collision scheme |
| Same tool name on 2 servers -> handle + document | Prefix `serverSlug__toolName`, mapping table, description `[slug]` |
| Slow/dead upstream must not break others (timeout + error) | Per-server `httpx.Timeout`, `asyncio.wait_for(10s)`, `gather(return_exceptions)`, circuit breaker |
| Upstream creds stay server-side | Fernet-encrypted column, never serialized to API, injected at proxy time |
| At least 3 upstreams | Woo + 2 chosen (recommend: `Time MCP` + `Filesystem/Memory MCP` or `GitHub MCP`) — rationale in 01 |

### 6.4 Team & Access
| Req | Answer |
|---|---|
| Roles: admin, member | `users.role` enum, RBAC middleware |
| Per-user API keys, revocable, hashed | `api_keys` table, `argon2id` hash + `sha256` lookup, `revoked_at`, plaintext once |
| Audit log (user, server, tool, ts, duration, outcome) | `audit_logs` partitioned table, async queue writer, dashboard query |

### 6.5 Chat Agent
| Req | Answer |
|---|---|
| Chat in dashboard, LLM calls tools via gateway, shows calls | React chat + FastAPI `/chat/completions` endpoint, server-side tool loop |
| Acts as logged-in user (audit attribution) | Impersonation via internal service JWT / ephemeral key tied to session user |
| Model/provider your choice, free/local ok | Default: OpenAI `gpt-4o-mini` or Anthropic free tier; local Ollama fallback documented | 
| LLM keys as Secrets | `Secret llm-secrets` |

---

## 7. Bonus — When to Attempt

**Gate:** Only after core E2E green + probes + policies + demo rehearsed twice.

| Bonus | Effort | Wow Factor | Recommendation |
|---|---|---|---|
| **Multi-store provisioning** | High | Highest (provision Helm per namespace via K8s API) | Do if you have 4+ days buffer. Strongest differentiator. |
| VPS deployment (k3s) | Medium | High | **Do** — cheap Hetzner/Vultr $6/mo, proves `values-prod.yaml` is real. |
| Tool permissions (per-role) | Low-Mid | High (members read-only) | **Do** — small code, big security story. |
| OAuth on gateway | Medium | Medium | Skip unless you know OAuth cold. |
| Many-tools handling (search+execute) | Mid | High for scale story | Mention as design, implement `search_tools` meta-tool. |
| Hosted MCP servers (image -> deploy) | High | Medium | Skip — overlaps multi-store. |
| Security hardening (SSRF, RBAC, NP) | Low | **Must do** | Do by default — SSRF validator + deny-by-default NP. |
| Scaling (multi-replica) | Low | Medium | Run 2 replicas + show sessionless design works. |
| Observability (metrics) | Low | Medium | Prometheus + Grafana dashboard (optional). |
| Upgrades/rollback | Low | Medium | Document `helm upgrade --atomic` + DB migration Job. |

**Pick 2-3 deep:** Recommended set = `VPS deploy` + `per-tool permissions` + `SSRF+NetworkPolicy hardening` + (if time) `search_tools` meta-tool. That is 80% of wow with 30% of effort.

---

## 8. Deliverables Checklist (repo root)

```
README.md                           # local setup, VPS setup, order + client + chat how-to
helm/                               # charts + values-local/prod.yaml
src/
  woo-mcp/                          # Woo MCP server
  gateway/                          # FastAPI gateway
  dashboard/                        # React
docs/                               # this folder (brain)
  00_OVERVIEW_AND_TRACEABILITY.md   # this file
  01_ARCHITECTURE.md
  02_MCP_PROTOCOL.md
  03_WOOCOMMERCE_MCP_SERVER.md
  04_GATEWAY_BACKEND.md
  05_DASHBOARD_AND_CHAT_AGENT.md
  06_KUBERNETES_AND_HELM.md
  07_SECURITY_AND_THREAT_MODEL.md
  08_IMPLEMENTATION_ROADMAP.md
  09_STAND_OUT_AND_BONUS.md
  10_BONUS_MULTI_STORE.md           # full bonus blueprint (optional, gate after Day 12)
 SYSTEM_DESIGN_AND_TRADEOFFS.md      # short note (required)
 THREAT_MODEL.md                     # short note (required)
```

---

## 9. Tech Stack Decision (Python)

| Layer | Choice | Why |
|---|---|---|
| MCP servers & gateway | **Python 3.12 + FastAPI + `mcp` SDK + `httpx`** | Native Streamable HTTP, async, matches brief's "python" preference, easy Helm Docker |
| Woo store | `wordpress:6.6-php8.2-apache` + `mariadb:11.4` | Official images, minimal custom Dockerfile (bake Woo plugin) |
| Gateway DB | **PostgreSQL 16** (`postgres:16-alpine`) | Concurrent audit writes, partitioning, `pgcrypto`; SQLite would serialize |
| Dashboard | **React + Vite + TypeScript + Tailwind + TanStack Query** | Fast to build, matches FastAPI OpenAPI |
| LLM | **OpenAI `gpt-4o-mini`** (or `gpt-4.1-mini`) with env switch to Ollama | Free tier works, tool calling mature; fallback documented |
| K8s local | **Kind** | Fastest CI, `extraPortMappings`, `standard` StorageClass |
| K8s prod | **k3s** single node | Lightweight, `local-path` + `klipper-lb`, easy VPS |
| Ingress | **ingress-nginx** (both envs) | Same controller local+prod; param via `ingressClassName` |
| Secrets | K8s `Secret` + `SealedSecrets` optional | No hardcoded values; hashed API keys in DB |

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Woo REST API flaky / auth fails | MCP tools fail | Helm Job seeds Consumer Key/Secret + health check; Woo-MCP readiness probes Woo API |
| MCP SDK breaking changes (2025-06-18) | Gateway/MCP compat | Pin `mcp==1.12.*`, test Initialize+tools/list+call against Inspector |
| Kind networking / Ingress not reachable | Demo fails | Document `nip.io` fallback + `kubectl port-forward` emergency path |
| Audit log overload | DB bloat | Partition by month, retention 90d, async queue + `maxsize 10k` |
| LLM tool loop infinite | Cost/spin | `max_iters=8`, `overall_timeout=60s`, `max_tool_calls=20` |
| SSRF bypass via DNS rebinding | Security fail grade | Resolve-on-every-request + IP blocklist + `follow_redirects=False` |

---

*Next: `01_ARCHITECTURE.md` draws the boxes and arrows that make the table above real.*
