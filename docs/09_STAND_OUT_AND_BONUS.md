# 09 — Stand-Out & Bonus Strategy

> Depth in one area beats thin attempts at all. Pick 2-3 deep.

## 1. Recommended Picks (max wow / effort)

| Priority | Item | Effort | What to Build | Where to Find |
|---|---|---|---|---|
| **Must** | Security hardening (SSRF + NP + hashed keys) | Low | `registry/validator.py`, `NetworkPolicy`, `argon2id` | 04_GATEWAY_BACKEND, 07_SECURITY |
| **Do** | VPS deployment (k3s) | Medium | Same chart on VPS, `values-prod.yaml`, TLS optional | 06_KUBERNETES |
| **Do** | Tool permissions (per-role) | Low-Med | `permissions` table, `can_call` filter on list+call, UI matrix | 04_GATEWAY_BACKEND |
| **Consider** | Many-tools handling (`search_tools`) | Mid | Meta-tool that searches catalog then executes | below |
| **If time** | Multi-store provisioning | High | Per-namespace Helm release via K8s API + NetworkPolicy | below |

**Do NOT attempt more than the above unless Days 1-12 are green twice.**

---

## 2. Bonus Deep Dives

### 2.1 Multi-Store Provisioning (optional, highest wow) — full blueprint in `10_BONUS_MULTI_STORE.md`

```
Dashboard -> POST /api/stores {name, slug} -> Gateway Provisioner
  -> Create Namespace store-<slug> with ResourceQuota + LimitRange + NetworkPolicy
  -> Helm install store chart (wordpress+db+pvc+ingress) via Kubernetes API (helm SDK or raw apply)
  -> Wait for WP ready, create Woo CK/CS, create Secret woo-secrets-<slug>
  -> Deploy woo-mcp-<slug> in that namespace
  -> Register upstream {slug: store-<slug>, url: http://woo-mcp.store-<slug>.svc:8000/mcp} in gateway
  -> Poll status: Provisioning -> Ready/Failed
Delete: remove namespace (cascades PVC, Secret, MCP registration) via finalizer
```

- **Isolation:** `NetworkPolicy` per store namespace `podSelector: {}` deny cross-namespace; show `kubectl exec` from `store-a` can't reach `store-b-mariadb`.
- **Guardrails:** `ResourceQuota` 1cpu/1Gi, `LimitRange`, `maxStoresPerUser=3`, `provisionTimeout=10m`.
- **Recovery:** Job is idempotent (`helm upgrade --install`); provisioner reconciles on restart (list namespaces with label `urumi.io/store=true`).

**Test:** Chat "compare today's orders across 2 stores" -> delete one store -> its tools gone.

> Detailed K8s resources, tool naming `store_<slug>__*`, API, isolation proof `curl` commands, RBAC, helm vs raw, and interview defence are in `10_BONUS_MULTI_STORE.md`.

### 2.2 Many Tools (`search_tools` meta-tool)

- Problem: 10 servers × 50 tools = 500 tools -> LLM context overflow.
- Solution: Gateway exposes only `search_tools(query)` + `execute_tool(name, args)`; LLM first searches, then executes.
```python
@mcp.tool()
async def search_tools(query: str) -> str:
  # vector/semantic or LIKE on exposed_name+description
  return json.dumps([t for t in catalog if query.lower() in t.description.lower()][:10])

@mcp.tool()
async def execute_tool(name: str, arguments: dict) -> str:
  return await gateway_call_tool(user, name, arguments)
```
- Document as trade-off: fewer tokens, extra hop, but scales.

### 2.3 Hosted MCP Servers (image -> deploy)

- Admin adds server by `image: ghcr.io/org/mcp-server:latest` instead of URL.
- Gateway creates `Deployment` + `Secret` (creds) + `Service` (ClusterIP) + `NetworkPolicy`, probes `/mcp`, registers automatically.
- Teardown deletes all resources via ownerReference.
- Overlaps multi-store; attempt only if multi-store is out of scope.

---

## 3. How to Stand Out Without Bonus

These polish items impress reviewers more than a half-baked bonus:

- **One Helm chart, two values files, zero code changes** — prove with `diff values-local.yaml values-prod.yaml`.
- **NetworkPolicy demo:** `kubectl run curl --rm -i --restart=Never --image=curlimages/curl -- curl -m5 http://woo-mcp:8000/mcp` -> blocked vs `gateway` pod -> allowed.
- **Audit log live tail:** `kubectl logs -f gateway` shows `X-Request-ID` + JSON structured logs.
- **Helm upgrade/rollback:** `helm upgrade --atomic` with image tag bump, then `helm rollback`.
- **Metrics:** `/metrics` Prometheus + Grafana screenshot (tool latency, circuit state).
- **Scaling:** `kubectl scale deploy gateway --replicas=2` -> Inspector still works (stateless proof).

---

## 4. What to Mention in "System Design and Tradeoffs" Note

- Aggregation stateless vs session (we chose stateless for replica scaling, no Redis).
- REST vs WP-CLI vs DB (REST preserves hooks, no pod exec).
- Postgres vs SQLite (concurrent audit, multi-replica).
- Prefix collision vs wrapper (prefix is spec-compliant, LLM-friendly).
- SSRF validator depth (write + DNS resolve + NP).
- LLM choice (gpt-4o-mini vs Ollama local) — we abstract provider.

---

## 5. Checklist for Submission Form

- [ ] GitHub repo public, `README.md` has local + VPS + client + chat instructions
- [ ] `helm/` + `values-local.yaml` + `values-prod.yaml` present, `helm lint` passes
- [ ] `SYSTEM_DESIGN_AND_TRADEOFFS.md` + `THREAT_MODEL.md` present
- [ ] Demo video 8-12 min covers 6 chapters from brief, with two users live
- [ ] Form: https://forms.gle/nftwgyNeenSDmiRb6 — video link + repo link
