# Urumi AI — MCP Gateway on Kubernetes (Brain Docs)

> **Status:** Days 0-4 complete and verified live on Kind — store + MariaDB + Ingress + setup Job + Woo MCP server (Layer 2: 6 tools over Streamable HTTP, ClusterIP-only, gateway-only NetworkPolicy). See `docs/05a_DAY_0-2_CHECKLIST.md` and `docs/05b_DAY_3-4_CHECKLIST.md`. Gateway + dashboard next. Take-home due **26 Oct 2026, 11:59 PM IST**.

## What This Is

The assignment: **WooCommerce hosting + Team MCP Gateway on Kubernetes + Helm**, with a custom Woo MCP server, a gateway that aggregates N Streamable-HTTP servers behind one `/mcp` endpoint, a React dashboard, and a chat agent that calls tools via the gateway as the logged-in user.

Evaluation: working core > unfinished bonus; must demo E2E with 2 users (chat + MCP client), revocation, disable, kill-pod isolation, audit log.

## How to Navigate the Brain

| Doc | Read When |
|---|---|
| `docs/00_OVERVIEW_AND_TRACEABILITY.md` | First — traceability matrix, DoD demo script, mandatory checklist, stack, bonus gate |
| `docs/01_ARCHITECTURE.md` | Boxes/arrows: 4 layers, 3 request flows, topology, resource table |
| `docs/02_MCP_PROTOCOL.md` | MCP Streamable HTTP wire (initialize/tools/list/call), aggregation, collision, SDK |
| `docs/03_WOOCOMMERCE_MCP_SERVER.md` | 6 tools contract, Woo REST vs WP-CLI vs DB, K8s wiring |
| `docs/04_GATEWAY_BACKEND.md` | Gateway modules, data models, auth/SSRF/audit/breaker |
| `docs/05_DASHBOARD_AND_CHAT_AGENT.md` | React pages, chat server-side tool loop, SSE, anti-injection |
| `docs/06_KUBERNETES_AND_HELM.md` | Kind vs k3s, Helm chart, Ingress/hosts, probes, NP, PVC |
| `docs/05a_DAY_0-2_CHECKLIST.md` | **Day 0-2 done + verified** — what shipped, gotchas solved, what's left |
| `docs/05b_DAY_3-4_CHECKLIST.md` | **Day 3-4 done + verified** — Woo MCP (Layer 2): 6 tools, probes, isolation, error mapping |
| `docs/DECISIONS.md` | Decision log (ADR): why each choice, with rejected alternatives |
| `docs/07_SECURITY_AND_THREAT_MODEL.md` | 6 threats + mitigations, interview talk-track (long form of `THREAT_MODEL.md`) |
| `docs/08_IMPLEMENTATION_ROADMAP.md` | 14-day day-by-day plan with exit criteria |
| `docs/09_STAND_OUT_AND_BONUS.md` | Which bonuses to pick (depth > breadth), multi-store summary |
| `docs/10_BONUS_MULTI_STORE.md` | Full multi-store provisioning blueprint (optional bonus, gated) |
| `SYSTEM_DESIGN_AND_TRADEOFFS.md` | Required short note (tradeoffs + prod deltas) |
| `THREAT_MODEL.md` | Required short note (4 threats + SSRF table) |

## Quick Demo Script (what you will record)

1. Store: open `store.<domain>` → add to cart → COD checkout → Woo Admin order visible.
2. Chat as User A: "create product Urumi Tee $29.99" → storefront shows it; hand-place order; "what orders today?" → returns it.
3. Inspector as User B (gateway URL + other key): `tools/list` shows all 3 servers; same orders question succeeds; one prompt uses 2 servers.
4. Control: revoke B's key → 401; disable a server → tools vanish; kill woo-mcp pod → others work, dashboard Unreachable; audit shows all calls.

## Tech Stack (Python)

Python 3.12 · FastAPI · `mcp` SDK · `httpx` · Postgres 16 + SQLAlchemy async · React 18 + Vite + TS + Tailwind + TanStack Query · OpenAI `gpt-4o-mini` (swappable) · Kind (local) + k3s (VPS) · ingress-nginx · Helm (no Kustomize).

## Local Setup (verified)

```bash
make kind-up                                  # kind create cluster --name urumi --config kind-config.yaml
make ingress                                  # ingress-nginx for kind
make helm-local                              # secrets-local + helm upgrade --install (runs wp-setup hook)
make woo-mcp-image                            # Layer 2: build + import woo-mcp image into the kind node
make verify-store                             # lint, ps, wp-setup logs, store curl, woo-secrets
make verify-cod                               # COD offered at checkout (Store API) + COD option value
make verify-mcp                               # Layer 2: MCP handshake, 6 tools, error mapping, isolation
open http://store.127.0.0.1.nip.io             # title: "Urumi Store" (COD checkout works)
# MCP Inspector against the Woo MCP server:
kubectl port-forward -n urumi svc/urumi-woo-mcp 8000:8000   # then connect to http://localhost:8000/mcp
```

VPS is same `helm/` + `helm/values-prod.yaml` (domain, storageClass, TLS). See `docs/06_KUBERNETES_AND_HELM.md`.

## Submission (when ready)

- Demo video (chapters: design, K8s, MCP internals, security, chat, local→VPS) + GitHub repo → https://forms.gle/nftwgyNeenSDmiRb6

## Next Step

`git add -A && git commit -m "Day 0-2: store on kind"`, then start `docs/08_IMPLEMENTATION_ROADMAP.md` Day 3-4 (`src/woo-mcp`). Core first, bonus only after Day 12 DoD passes twice.
