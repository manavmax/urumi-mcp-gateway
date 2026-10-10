# 10 — Bonus: Multi-Store Provisioning (Full Blueprint)

> **Status:** Optional bonus. **Gate:** Attempt only after core (Days 1-12) is green twice. This doc makes the bonus defensible end-to-end in interview + demo without hand-waving.

## 1. What the Brief Requires (verbatim mapping)

| Requirement | Test |
|---|---|
| Create & delete from dashboard; list stores with `Provisioning / Ready / Failed`, URL, created time; concurrent provision | Dashboard Stores page: Create modal -> row appears Provisioning -> Ready/Failed; create 2 at once |
| Kubernetes-native: each store via Helm/K8s API, own namespace, DB, Secrets, PVCs, Ingress | `kubectl get ns -l urumi.io/store=true` -> N namespaces each with PVC/Service/Ingress |
| Automatic MCP registration: each new store gets its own Woo MCP, registered without manual steps; tool names show store | Gateway `tools/list` after provision returns `store-a__list_products` + `store-b__list_products` |
| Clean teardown: delete removes namespace/PVCs/Secrets/MCP registration | Delete in dashboard -> namespace gone, tools gone from `tools/list` |
| Isolation: one store's MCP cannot reach another's DB/WordPress; show with NetworkPolicy | `curl` from `store-a` woo-mcp pod to `store-b` mariadb: blocked |
| Guardrails: ResourceQuota, LimitRange per store namespace, max stores per user, provisioning timeout | Quota/LimitRange visible via `kubectl get resourcequota,limitrange -n store-*` |
| Recovery: create is retry-safe; provisioner restart mid-provision either completes or fails cleanly | Kill gateway mid-provision -> on restart it reconciles to Ready or Failed with reason |

**Bonus test:** Chat "compare today's orders across two stores" (calls tools from both prefixed stores), then delete one store and show its tools/resources gone.

---

## 2. Architecture

```mermaid
flowchart TB
  subgraph Dashboard[Dashboard - Stores Page]
    UI[Create Store modal - name/slug]
  end
  subgraph Gateway[Gateway - Provisioner Module]
    API[POST /api/stores]
    CTRL[Store Controller - async Task + poller]
    REG[Registry - servers table]
  end
  subgraph K8sAPI[Kubernetes API]
    NS[Namespace store-<slug>]
    RQ[ResourceQuota]
    LR[LimitRange]
    NP[NetworkPolicies]
    PVC1[PVC wp-content]
    PVC2[PVC wp-data]
    SEC[Secrets]
    WP[WordPress Deploy]
    DB[(MariaDB StatefulSet)]
    MCP[woo-mcp Deploy]
    ING[Ingress store-<slug>.<domain>]
    SVCWP[Service wordpress]
    SVCMCP[Service woo-mcp]
  end

  UI -->|POST /api/stores {name,slug}| API
  API -->|insert stores row Provisioning + enqueue| CTRL
  CTRL -->|create via K8s API/Helm| K8sAPI
  K8sAPI -->|WP Ready + woo-mcp Ready| CTRL
  CTRL -->|create CK/CS Secret + probe /mcp + register| REG
  REG -.->|tools: store-a__*, store-b__*| Gateway
```

### 2.1 Per-Store K8s Resources (namespace `store-<slug>`)

```
Namespace: store-<slug>
  labels: {urumi.io/store: "true", urumi.io/owner: "<user-id>", urumi.io/slug: "<slug>"}
  annotations: {urumi.io/created-at: "2026-10-26T..."}
  ResourceQuota: {requests.cpu: 1, requests.memory: 1Gi, limits.cpu: 2, limits.memory: 2Gi, pvc: 2, pods: 5}
  LimitRange: {Container default 500m/512Mi, defaultRequest 100m/128Mi, max 1000m/1Gi, min 50m/64Mi}
  NetworkPolicy:
    - default-deny (Ingress+Egress deny all)
    - allow wordpress -> mariadb (3306 within namespace)
    - allow ingress-nginx -> wordpress (80)  # via namespaceSelector
    - allow gateway (in `urumi` ns) -> woo-mcp (8000)  # cross-namespace: from namespaceSelector urumi + podSelector gateway
    - allow DNS egress (53 UDP/TCP)
    - deny cross-store (no rule allows store-a pod -> store-b mariadb; default deny enforces)
  PVC: wp-content 5Gi RWO, wp-data 10Gi RWO (via StatefulSet)
  Secret: wp-secret, mariadb-secret, woo-secrets-<slug> (CK/CS + WOO_URL=http://wordpress.store-<slug>.svc.cluster.local)
  Service: wordpress ClusterIP 80, mariadb ClusterIP 3306, woo-mcp ClusterIP 8000
  Deployment: wordpress 1x, woo-mcp 1x; StatefulSet: mariadb 1x
  Ingress: host `store-<slug>.<domain>` -> wordpress:80 (path /)
```

**Helm approach:** Reuse a `charts/store-template/` subchart (word press+db+woo-mcp) installed via `helm upgrade --install store-<slug> ./charts/store-template -n store-<slug> --set slug=<slug>,domain=<domain>,storageClass=<class>` invoked by gateway. Alternatively raw `kubectl apply` manifests templated with `jinja2` — either is "Kubernetes API". Helm is preferred for upgrade/rollback.

### 2.2 Gateway Provisioner — Data Model

```sql
CREATE TABLE stores (
  id UUID PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL CHECK (slug ~ '^[a-z0-9-]{3,30}$'),
  name TEXT NOT NULL,
  owner_id UUID REFERENCES users(id),
  status TEXT CHECK (status IN ('Provisioning','Ready','Failed')) NOT NULL DEFAULT 'Provisioning',
  url TEXT,  -- https://store-<slug>.<domain>
  namespace TEXT NOT NULL,
  helm_release TEXT, -- store-<slug>
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON stores(status); CREATE INDEX ON stores(owner_id);
-- link to MCP registry: servers.slug = 'store-'||stores.slug
```

```sql
-- servers table already has slug; for store servers add:
-- server_type: 'builtin' | 'store' | 'external'
ALTER TABLE servers ADD COLUMN server_type TEXT DEFAULT 'external';
ALTER TABLE servers ADD COLUMN store_id UUID REFERENCES stores(id) ON DELETE CASCADE;
```

### 2.3 Tool Naming for Multi-Store

```
exposed_name = f"store_{slug}__{tool}"   # e.g. store_urumi-a__list_products, store_urumi-b__list_orders
description  = f"[{slug}] {orig_desc}"   # [urumi-a] List products
```

- Keeps collision-free across N stores + builtin `woo__*` (rename builtin to `store_main__*` or keep `woo__*` and stores as `store-*__*` — document choice; we keep `woo__*` for main + `store-<slug>__*` for provisioned).
- Chat "compare today's orders across two stores" -> LLM calls `store_urumi-a__list_orders` and `store_urumi-b__list_orders`.

---

## 3. Lifecycle & API

### 3.1 Create (retry-safe, concurrent)

```
POST /api/stores {name, slug}  (admin/member; enforce maxStoresPerUser=3)
-> validate slug, check quota (count where owner_id=:user and status != Failed <3)
-> insert stores row Provisioning, return 202 {id, status:Provisioning}
-> background task: provision(slug)  # asyncio.create_task, timeout 10m
```

`provision(slug)` steps (each idempotent):

1. Create Namespace `store-<slug>` (if exists, adopt if labels match, else 409).
2. Apply ResourceQuota, LimitRange, NetworkPolicies.
3. Create Secrets (wp/mariadb random passwords; woo CK/CS will be created after WP ready).
4. `helm upgrade --install store-<slug> charts/store-template -n store-<slug>` (idempotent).
5. Poll `Deployment wordpress` + `StatefulSet mariadb` Ready (timeout 8m).
6. Create Woo CK/CS via WP Job or REST (after WP ready), create Secret `woo-secrets-<slug>`, roll woo-mcp.
7. Poll `Deployment woo-mcp` Ready.
8. Health probe `POST http://woo-mcp.store-<slug>.svc.cluster.local:8000/mcp {tools/list}` (timeout 10s, retry 3).
9. Register/Upsert `servers` row `{slug: store-<slug>, url: http://woo-mcp.store-<slug>.svc.cluster.local:8000/mcp, server_type: store, store_id}`; mark `stores.status=Ready, url=https://store-<slug>.<domain>`.

Failure at any step -> `stores.status=Failed, error=step+message` (visible in dashboard, retry via `POST /api/stores/:id/retry`).

### 3.2 Delete (clean teardown)

```
DELETE /api/stores/:id
-> delete servers row where store_id=:id (tools vanish from catalog immediately)
-> delete Namespace store-<slug> (cascades all PVC/Secrets/Deployments)
-> poll namespace gone (timeout 60s)
-> delete stores row or mark Deleted (keep audit)
```

MCP registration cleanup is immediate; even if namespace deletion is async, `tools/list` no longer returns its tools.

### 3.3 Status & Polling

```
GET /api/stores           -> [{id, slug, name, status, url, created_at, error}]
GET /api/stores/:id       -> single + events
GET /api/stores/:id/logs  -> provisioner logs (last 100 lines)
```

Dashboard polls `GET /api/stores` every 3s while any `Provisioning`.

---

## 4. Isolation Proof (NetworkPolicy)

**Default deny per store namespace:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: default-deny, namespace: store-urumi-a}
spec: {podSelector: {}, policyTypes: [Ingress, Egress]}
```

**Allow gateway cross-namespace to woo-mcp:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-gateway-to-woo-mcp, namespace: store-urumi-a}
spec:
  podSelector: {matchLabels: {app: woo-mcp}}
  policyTypes: [Ingress]
  ingress:
  - from:
    - namespaceSelector: {matchLabels: {name: urumi}}
      podSelector: {matchLabels: {app: gateway}}
    ports: [{port: 8000}]
```

**Deny cross-store:** No rule allows `store-urumi-a` pods to reach `store-urumi-b` mariadb; default deny blocks. Demo:

```bash
kubectl exec -n store-urumi-a deploy/woo-mcp -- curl -m5 http://mariadb.store-urumi-b.svc.cluster.local:3306
# -> timeout / connection refused (blocked)
kubectl exec -n store-urumi-a deploy/woo-mcp -- curl -m5 http://mariadb.store-urumi-a.svc.cluster.local:3306
# -> not blocked (within namespace, wordpress->mariadb rule) — or via app succeeds
```

Show both in video.

---

## 5. Guardrails

| Guardrail | Value | Enforcement |
|---|---|---|
| ResourceQuota per store NS | cpu 1/2, mem 1Gi/2Gi, pvc 2, pods 5 | `ResourceQuota` object |
| LimitRange | default 500m/512Mi, request 100m/128Mi | `LimitRange` |
| maxStoresPerUser | 3 (configurable `MAX_STORES_PER_USER`) | check before enqueue |
| provisionTimeout | 10m per store | `asyncio.wait_for(600)` -> mark Failed |
| concurrent limit | 3 parallel provisions (`Semaphore(3)`) | avoid API server thunder |

---

## 6. Recovery & Idempotency

- **Idempotent create:** `helm upgrade --install` + `kubectl apply` with `create-or-update` are safe to retry. Secrets use `create-or-keep` (don't regenerate passwords on retry).
- **Crash mid-provision:** On gateway restart, `lifespan` runs `reconcile()`:
  ```python
  for s in SELECT * FROM stores WHERE status='Provisioning':
    if namespace not exists -> mark Failed (reason: interrupted)
    elif helm release exists + all Deployments Ready -> continue step 6-9
    elif timeout exceeded -> mark Failed
  ```
- **Helm release drift:** `helm get manifest` check; `helm upgrade` fixes.
- **Finalizer on stores row** ensures delete always cleans namespace even if gateway crashes mid-delete.

---

## 7. Chat Test for Bonus

1. Provision `store-a` and `store-b` (concurrent) -> both Ready.
2. Seed one order in each via storefront.
3. Chat as User A: "Compare today's orders across store-a and store-b" -> LLM calls `store_urumi-a__list_orders {after: today}` + `store_urumi-b__list_orders {after: today}` -> answers with both.
4. Delete `store-b` from dashboard -> `kubectl get ns store-urumi-b` gone, `tools/list` via Inspector no longer has `store_urumi-b__*`, chat "list orders from store-b" fails gracefully.
5. Audit shows both `store_urumi-a__*` and `store_urumi-b__*` calls.

---

## 8. Tradeoffs & What Changes for Production

- **Namespace per store** vs labels in one namespace: namespace gives strong isolation (quota, policy, PVC) but N=100 needs API server tuning; single-namespace with label isolation is lighter but weaker.
- **Helm SDK** vs raw apply: Helm gives upgrade/rollback but needs helm binary in gateway image; raw apply is simpler but no `helm rollback`.
- **Storage:** `values-local.yaml` -> `standard`/`local-path` (hostPath); prod -> `longhorn` or cloud block storage with `Retain`.
- **Ingress:** Wildcard `*.store.<domain>` or per-store host; cert-manager wildcard `*.urumi.store` with DNS-01.
- **Provisioner RBAC:** Gateway ServiceAccount needs `create/get/list/delete` on `namespaces, resourcequotas, limitranges, networkpolicies, secrets, pvc, deployments, services, ingresses, jobs` — minimal, scoped via Role/RoleBinding per namespace pattern or ClusterRole with label selector.

---

## 9. Implementation Sketch (files)

```
src/gateway/provisioner/
  api.py            # POST /api/stores, GET, DELETE, retry
  controller.py     # provision(slug), delete(slug), reconcile()
  helm.py           # helm upgrade --install wrapper (subprocess or helm SDK)
  k8s.py            # light kube client (kubernetes-asyncio) + helpers
  templates/        # store-template chart or manifests
charts/store-template/
  Chart.yaml, values.yaml, templates/{namespace,quota,limitrange,networkpolicy,pvc,secret,wordpress,mariadb,woo-mcp,service,ingress}
```

Gateway `Dockerfile` adds `helm` binary if using Helm; else pure `kubernetes` Python client.

---

## 10. Interview Defence (30s)

> "Each store is a namespace with its own quotas, policies, PVCs and ingress, provisioned via Helm through the K8s API from the dashboard; gateway registers its woo-mcp automatically with store-prefixed tools, so chat can compare across stores. Delete cascades the namespace and deregisters the server. NetworkPolicy deny-by-default proves isolation, and the provisioner reconciles on restart so retries are safe."
