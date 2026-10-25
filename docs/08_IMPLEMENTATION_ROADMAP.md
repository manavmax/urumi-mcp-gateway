# 08: Implementation Roadmap (14-Day Plan, Python)

> **Principle:** Working core first. No bonus until E2E green. Each day ends with a runnable slice.

## 0. Pre Day 0: Repo & Tooling (0.5 day)

- [x] `git init` + `README.md` skeleton + `.gitignore` (`.env`, `*.key`, `__pycache__`)
- [x] `helm create` replacement with structure from `06_KUBERNETES_AND_HELM.md`
- [x] `kind-config.yaml`, `Makefile` (`make kind-up`, `make helm-local`, `make helm-prod`, `make lint`)
- [x] Pin versions: `mcp==1.12.*`, `fastapi==0.115.*`, `httpx==0.27.*`, `sqlalchemy[asyncio]==2.0.*`, `asyncpg`, `argon2-cffi`, `cryptography`, `openai==1.*`
- [x] `docker-compose.yml` for local dev without Kind (optional fast loop)

> **Done 2026-10-10**: verified live on `kind-urumi`, rev 12.

---

## Days 1-2: Store on Kind (Layer 1)

- [x] WordPress + MariaDB Helm templates + PVCs + Services + Ingress (`store.127.0.0.1.nip.io`)
- [x] `wp-setup` Job: `wp core install`, `woocommerce` activate, `install_pages`, seed 2 products
- [x] Create Woo Consumer Key/Secret (Read/Write), store in `woo-secrets` Secret
- [x] Manual test: open storefront, add to cart, checkout COD, verify in Woo Admin
- [x] Add probes + resources + NetworkPolicy (wordpress->mariadb)
- [x] **Exit:** `curl store.127.0.0.1.nip.io` works; `helm lint` passes

## Days 3-4: Woo MCP Server (Layer 2)

- [x] `src/woo-mcp/`: FastAPI + `mcp` SDK, 6 tools via `httpx` to `wc/v3`
- [x] `WooRestClient` with CK/CS Basic auth, timeout 10s, error mapping
- [x] Dockerfile + K8s Deployment/Service (ClusterIP) + probes (readyz hits Woo)
- [x] Test via `kubectl port-forward` + MCP Inspector: `tools/list` + `call create_product` -> verify on storefront
- [x] NetworkPolicy: only gateway can reach `woo-mcp`
- **Exit:** `npx @modelcontextprotocol/inspector` via `port-forward` shows 6 tools, all working

> **Done 2026-10-10**: 21-check run + `make verify-mcp`.

## Days 5-7: Gateway Core (Layer 3, hardest)

- [x] `src/gateway/`: FastAPI + PG + SQLAlchemy async + Alembic (`users, api_keys, servers, tools, audit_logs`)
- [x] Auth: API key generate/hash/verify/revoke + RBAC (admin/member) + session for dashboard
- [x] Registry CRUD: `POST /api/servers` with SSRF validator + Fernet encrypt; seed `Woo-MCP` on startup
- [x] MCP aggregation: `POST/GET /mcp`: `tools/list` fan out (gather+timeout) + `tools/call` routing (prefix `slug__tool`) + audit queue
- [x] Health loop + circuit breaker + seeding 2nd/3rd servers (time + memory)
- [x] Dashboard shell: React login + Servers page (list/add/edit/disable) + Members/Keys + Audit table (read only first)
- **Exit:** Inspector with gateway URL + user key shows aggregated tools from 3 servers; `tools/call woo__create_product` creates product; audit row appears

> **Done 2026-10-12**: `verify-gateway`: 23/23 PASS: handshake, 11-tool fan out across 3 servers, 3-server routing, admin login with the Secret password, SSRF, audit; plus 29 unit tests via `make test`.

## Days 8-9: Chat Agent (Layer 4) + Dashboard Polish

- [x] `src/gateway/chat/agent.py`: OpenAI tool loop (8 iters, SSE stream), impersonates logged in user; model + endpoint now come from `gateway.llm.*` values, not source
- [x] `POST /api/chat/completions` (SSE) + React `Chat.tsx` (tokens + tool chips)
- [x] RBAC filtering for chat tools + redaction + sanitization + system prompt
- [ ] Dashboard polish: status badges, tool drawers, key copy once, audit filters, chat UX: pages ship, but this pass is not reviewed/demoed
- **Exit:** Chat as User A "create product" + "what orders today?" shows tool chips + audit attribution

> **Code complete, exit criterion NOT demonstrated**: the chat endpoint answers
> `200 {"content": "Chat is not configured …"}` (verified) because the chart deliberately
> leaves the `gateway-llm` Secret's `OPENAI_API_KEY` empty until an operator supplies a
> real key (`ADR-022`; it used to be documented as a key on `gateway-secrets`). The streaming
> tool loop, tool chips and chat audit attribution have therefore never run end to end:
> treat Days 8-9 as **code complete, demo pending**, not done.

## Day 10: Hardening & K8s Polish

- [ ] Timeouts everywhere, `follow_redirects=False`, DNS `re-validate`, `X-Request-ID`, structured logs
- [ ] Probes/resources on all workloads, `securityContext`, `NetworkPolicy` deny by default verified (`kubectl get networkpolicy`, `curl` from disallowed pod fails)
- [ ] Secrets: no hardcode, `values-local.yaml` vs `values-prod.yaml` diff documented, `helm lint` + `kube-linter`
- [ ] Rate limit (per key 60/min) + `search_tools` meta tool if doing "many tools" stand out
- **Exit:** `helm template` shows no plaintext secrets; `kubectl exec` disallowed pod -> `curl woo-mcp:8000` blocked

## Day 11: VPS (k3s) Deployment (same charts)

- [ ] Provision $6/mo VPS, install k3s, `ingress-nginx`, (optional) `cert-manager` + letsencrypt
- [ ] `helm upgrade --install urumi ./helm -f values-prod.yaml`: verify store + dashboard + /mcp from internet
- [ ] Document `what changes through values` in README + `SYSTEM_DESIGN_AND_TRADEOFFS.md`
- **Exit:** VPS URLs work; demo can be recorded against either env

## Day 12: Demo Rehearsal + Definition of Done

- [ ] Run full DoD script with 2 users (User A admin, User B member) on Kind + VPS:
  - Store checkout, chat create_product + list_orders, Inspector list/call, cross server prompt, revoke key -> 401, disable server -> tools vanish, kill pod -> Unreachable + others work, audit check
- [ ] Fix flakes (Woo auth, timeout, CORS, Ingress host)
- [ ] Time the video: aim 8-12 min, one take
- **Exit:** DoD passes twice consecutively without manual fix

## Day 13: Docs & Video

- [ ] `README.md` (local setup, VPS setup, order + client + chat how to)
- [ ] `SYSTEM_DESIGN_AND_TRADEOFFS.md` + `THREAT_MODEL.md` (short, required)
- [ ] Record demo video (chapters: system design, K8s, MCP internals, security, chat, local->VPS)
- [ ] `helm upgrade --atomic` + `helm rollback` demo tested

## Day 14: Buffer / Bonus (only if core green)

- [ ] Pick 1-2: per tool permissions UI, `search_tools` meta tool, or start multi store (see `10_BONUS_MULTI_STORE.md`; gate: only after Day 12 DoD passed twice)
- [ ] Final `helm lint`, `git tag`, push, fill submission form

---

## 2. Risk Plan

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Woo CK/CS not created | Med | MCP tools 401 | Helm Job + docs for manual `Woo > REST API > Add Key`; readiness gate |
| MCP SDK version drift | Med | handshake fails | Pin `mcp==1.12.*`, test Inspector after each bump |
| Kind Ingress unreachable | Med | demo fails | `nip.io` + `kubectl port-forward` fallback documented |
| LLM rate limit / no key | Low | chat fails | Mock mode (echo tools) + env switch; truncate output |
| Audit DB bloat | Low | PG slow | Partition + retention 90d, queue maxsize |
| Scope creep to bonus | **High** | core unfinished | **Gate: Day 12 DoD must pass before bonus** |

---

## 3. Daily Verification Commands

```bash# DoD slice
curl -s store.127.0.0.1.nip.io | head
kubectl get pods -n urumi && kubectl get ingress -n urumi && kubectl get pvc -n urumi
kubectl get svc woo-mcp -n urumi  # ClusterIP
# MCP
npx @modelcontextprotocol/inspector  # connect to gateway /mcp with Bearer key
# Audit
curl -s dashboard.127.0.0.1.nip.io/api/audit -H "Cookie: session=..." | jq
# Revoke
curl -X DELETE dashboard.127.0.0.1.nip.io/api/keys/<id> -H "X-CSRF-Token: $CSRF"
curl -s dashboard.127.0.0.1.nip.io/mcp -H "Authorization: Bearer <revoked>" # -> 401
# Kill
kubectl delete pod -l app=woo-mcp -n urumi && kubectl get pods -w
```
---

## 4. Definition of "Done" for This Plan (handover to coding)

- [ ] All `docs/00-09` read and understood (can explain probes, SSRF, prefix, stateless)
- [ ] `helm/` skeleton created, `kind create cluster` works
- [ ] Ready to implement Days 1-2 without reresearching