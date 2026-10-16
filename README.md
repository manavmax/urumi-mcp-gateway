# Urumi AI — MCP Gateway on Kubernetes (Brain Docs)

> **Status:** Days 0-7 complete and verified live on Kind — store + MariaDB + Ingress + setup Job + Woo MCP server (Layer 2: 6 tools) **and Layer 3** (gateway + dashboard + 3-server `/mcp` aggregation, `verify-gateway` 23/23 PASS + `make test` 29 unit tests). Days 8-9 (chat exit demo) are code-complete but un-demonstrated: the LLM key is empty by design until an operator supplies one (ADR-022). Take-home due **26 Oct 2026, 11:59 PM IST**.

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

## Credentials & LLM wiring (no committed secrets)

Every credential is chart-generated at install into a Secret (`lookup`-guarded, `helm.sh/resource-policy: keep`), never committed: `mariadb-secret`, `wordpress-secret`, `pg-secret`, `gateway-secrets`, `gateway-admin`, `gateway-llm`, `demo-notes-token`, `wordpress-admin`.

```bash
make admin-password            # WordPress admin (Secret wordpress-admin)
make gateway-admin-password    # Gateway dashboard admin (Secret gateway-admin)
kubectl get secret gateway-llm -n urumi -o jsonpath='{.data.OPENAI_API_KEY}' | base64 -d | wc -c   # length only, never print
```

The chat assistant's LLM endpoint is values, not code — `gateway.llm` in `helm/values.yaml`:

| value | default | meaning |
|---|---|---|
| `gateway.llm.enabled` | `true` | injects `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` into the gateway pod |
| `gateway.llm.baseUrl` | `https://api.openai.com/v1` | any OpenAI-compatible endpoint works (groq, together, vllm, ...) — no code change |
| `gateway.llm.model` | `gpt-4o-mini` | model name passed to the chat completions call |
| `gateway.llm.existingSecret` | `""` | optional prod override: name of a pre-created Secret holding key `OPENAI_API_KEY`; when set the chart renders no `gateway-llm` Secret |

No API key is committed anywhere. The chart renders a `gateway-llm` Secret whose `OPENAI_API_KEY` is **empty until an operator supplies a real one** — deliberately not `randAlphaNum`, because a generated string is a guaranteed-invalid key and the honest failure is "chat is not configured" (ADR-022).

Apply a key. The recommended way asks for it with echo off, so it stays out of the shell history, any process list and any file:

```bash
printf 'Gemini API key (hidden): ' >&2
read -rs LLM_KEY
echo
kubectl -n urumi create secret generic gateway-llm --from-literal=OPENAI_API_KEY="$LLM_KEY" --dry-run=client -o yaml | kubectl apply -f -
unset LLM_KEY

# afterwards check the length, never the value:
kubectl get secret gateway-llm -n urumi -o jsonpath='{.data.OPENAI_API_KEY}' | base64 -d | wc -c
```

Rotating is the same command with a new key. In a script or CI, where the key already lives in a variable, skip the prompt:

```bash
kubectl -n urumi create secret generic gateway-llm --from-literal=OPENAI_API_KEY="$LLM_KEY" --dry-run=client -o yaml | kubectl apply -f -
```

**An upgrade never wipes the key.** Only the Secret's *existence* is unconditional; its *value* is `lookup`-guarded, so `helm upgrade` / `make helm-local` re-renders `gateway-llm` with the `OPENAI_API_KEY` already in the cluster instead of the empty default (ADR-016/022). Consequences worth knowing:

- A no-op upgrade is really a no-op: the value is unchanged, so `urumi.io/llm-secret-checksum` is unchanged, so the gateway pod is **not** restarted.
- `helm.sh/resource-policy: keep` means the Secret (and your key) survives `helm uninstall` and rollbacks.
- Only applying a *different* key changes the checksum, and that is what rolls the pod to pick up the new value.
- Nothing in `values.yaml` ever holds the key, so `git diff` and `helm get values` stay key-free; the chart's own file (`helm/templates/secrets.yaml`) says the same.

```bash
make verify-llm        # prove the live key: chat streams, multi-step tool loop, wrong-key error
```

Point `gateway.llm.existingSecret` at your own pre-created Secret (key `OPENAI_API_KEY`) to skip the chart-rendered one entirely.

## Tool permissions — restrict what members may call (ADR-033)

By default every member may use every tool of every enabled server (default
allow-all). Admins can restrict individual tools for the whole MEMBER role; admins
always have all tools.

**In the dashboard:** Servers → **Permissions** → tools grouped by server, one Member
toggle per tool (Admin is locked on for everyone) → **Save**. The restricted count is
shown in the panel head. Members see no permission UI; a restricted tool is simply
absent from their tools list, the Servers page and the member Overview "Tools I can use".

**With the API** (admin session cookie; the PUT is CSRF-protected, so grab the token
from `GET /api/auth/me`'s `csrf_token`):

```bash
TOKEN=$(curl -s -c /tmp/c.txt -X POST https://dashboard.<domain>/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@urumi.local","password":"..."}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["csrf_token"])')

# deny example: members keep woo__list_orders + woo__get_order, lose the write tools
curl -s -X PUT https://dashboard.<domain>/api/permissions \
  -b /tmp/c -H "X-CSRF-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"rules":[{"server_slug":"woo","tool_name":"woo__create_product"},
                {"server_slug":"woo","tool_name":"woo__update_order_status"}]}'

# allow everything again: empty rules list (or make demo-reset CONFIRM=yes)
curl -s -X PUT .../api/permissions -H "X-CSRF-Token: $CSRF" -d '{"rules":[]}'
```

Behaviour, in one paragraph: a denied tool disappears from `tools/list` for members and
a direct call to it is rejected with the standard unknown-tool error **before** any
upstream is contacted — the same enforcement core covers the external `/mcp` endpoint
and the chat agent, so a prompt-injection attempt that talks the model into naming a
denied tool is rejected too. Every denial is audited with outcome `permission_denied`.
Unknown server or tool names are rejected by the API (422); policy changes take effect
on the very next call (no cache). `make demo-reset` clears the table back to allow-all.

## Demo reset — `make demo-reset`

Between demo takes the cluster should be put back into a known state. `make demo-reset` does
that through official APIs only (Woo REST + the gateway's own models), it is **dry-run by
default**, and it refuses to run against anything but the local kind cluster.

```bash
make demo-reset                                # DRY RUN: prints what WOULD be deleted, changes nothing
make demo-reset CONFIRM=yes                    # performs the reset, then verifies 3 upstreams Connected + tools/list = 11
make demo-reset CONFIRM=yes ARGS=--with-demo-users   # additionally creates demo users A (admin) + B (member)
scripts/demo-reset.sh --check-only             # only the safety guard (exits 2 when it refuses)
```

The seed set (the products that survive) is an auditable file, not a hidden rule:
`scripts/demo-seeds.json`. Everything not matched there is test data.

| deletes | keeps |
|---|---|
| every WooCommerce product that is not a seed product (REST `force=true`) | the seed products (`URUMI-TEE-001`, `URUMI-HOODIE-001`), store settings, COD, tax/shipping |
| every WooCommerce order (all statuses) | all Kubernetes Secrets and PVCs, and the Helm release (the script never runs `helm`) |
| every row in `audit_logs` (ids restart at 1) | the gateway admin user `admin@urumi.local` and its API keys |
| every `tool_permissions` deny rule (back to default allow-all) | the 3 seeded upstreams `woo`/`time`/`notes`, their encrypted credentials, the Fernet state |
| every non-admin user + their API keys | any non-seeded server you added — it is listed in the summary, never deleted |
| all notes (in-memory store → `rollout restart` + `rollout status` of `urumi-demo-notes`) | |

Safety guarantees (ADR-032): refuses unless `kubectl config current-context` is a `kind-*`
cluster whose API server is on loopback and the namespace is `urumi`; the only cluster
object it mutates is the `urumi-demo-notes` Deployment; no credential is ever printed —
except the demo-user passwords/keys that `--with-demo-users` shows exactly once on the
terminal (never written to a file or log). A dry run only ever issues `kubectl get` /
`config` / `exec`; that invariant is pinned by `src/gateway/tests/test_demo_reset_safety.py`.

After a confirmed run the script prints a deleted/kept summary and verifies the demo
contract live: 3 upstreams `Connected` and `tools/list` returning 11 tools (woo 6, time 2,
notes 3).

## Submission (when ready)

- Demo video (chapters: design, K8s, MCP internals, security, chat, local→VPS) + GitHub repo → https://forms.gle/nftwgyNeenSDmiRb6

## Next Step

`git add -A && git commit -m "Day 0-2: store on kind"`, then start `docs/08_IMPLEMENTATION_ROADMAP.md` Day 3-4 (`src/woo-mcp`). Core first, bonus only after Day 12 DoD passes twice.
