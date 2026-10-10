# 06 — Kubernetes & Helm (Local ↔ VPS)

## 1. Helm Chart Structure (umbrella, single chart for grading)

```
helm/
  Chart.yaml                # name: urumi, version: 0.1.0, appVersion: 1.0.0
  values.yaml               # defaults (local-biased)
  values-local.yaml         # Kind: standard, nip.io, no TLS
  values-prod.yaml          # k3s: local-path/longhorn, real domain, TLS + cert-manager
  values.schema.json        # optional, validates values
  templates/
    _helpers.tpl
    namespace.yaml          # optional (or helm --namespace urumi --create-namespace)
    secrets.yaml            # gateway-secrets, woo-secrets, mariadb-secret, pg-secret (lookup, no hardcode)
    pvc-wordpress.yaml      # wp-content 5Gi
    pvc-mariadb.yaml        # via StatefulSet volumeClaimTemplates
    pvc-postgres.yaml       # pg-data 5Gi
    deployment-wordpress.yaml
    statefulset-mariadb.yaml
    statefulset-postgres.yaml  # or Deployment+PVC
    deployment-woo-mcp.yaml
    deployment-gateway.yaml
    deployment-dashboard.yaml
    service-*.yaml          # all ClusterIP
    ingress.yaml            # 2 hosts: store + dashboard
    networkpolicy.yaml      # default-deny + allows
    resourcequota.yaml      # conditional
    limitrange.yaml         # conditional
    jobs/
      wp-setup.yaml         # Helm post-install hook
    cronjob-backup.yaml     # optional
  charts/                   # vendored deps if any (none required)
```

---

## 2. Kind Local Setup (recommended)

### 2.1 kind-config.yaml

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
```

```bash
kind create cluster --name urumi --config kind-config.yaml
kubectl cluster-info
```

### 2.2 Ingress-nginx

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=120s
```

### 2.3 Local Domain (document both, use nip.io for zero-friction)

| Option | Hosts | Pros |
|---|---|---|
| **nip.io** (recommended) | `store.127.0.0.1.nip.io`, `dashboard.127.0.0.1.nip.io` | No `/etc/hosts` edit, works everywhere |
| `/etc/hosts` | `127.0.0.1 store.localtest.me dashboard.localtest.me` | Pretty, but manual edit |

Set `global.domain` accordingly:
```yaml
# values-local.yaml
global:
  domain: 127.0.0.1.nip.io
  ingressClass: nginx
  storageClass: standard  # Kind's default
  tlsEnabled: false
ingress:
  hosts:
    store: store.127.0.0.1.nip.io
    dashboard: dashboard.127.0.0.1.nip.io
```

---

## 3. VPS / k3s Production Setup (same charts, values diff)

### 3.1 VPS Provision (Hetzner/Vultr $6/mo or Oracle Free)

```bash
# on VPS
curl -sfL https://get.k3s.io | sh -s - --disable traefik  # or keep traefik and set ingressClass traefik
# kubeconfig at /etc/rancher/k3s/k3s.yaml
# point local kubectl: scp vps:/etc/rancher/k3s/k3s.yaml ~/.kube/k3s.yaml && KUBECONFIG=~/.kube/k3s.yaml kubectl get nodes

# install ingress-nginx if you disabled traefik
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml
```

### 3.2 What's Different (real values diff)

```yaml
# values-prod.yaml
global:
  domain: yourdomain.com  # or <vps-ip>.nip.io if no domain
  ingressClass: nginx
  storageClass: local-path  # k3s default; or longhorn if installed
  tlsEnabled: true
ingress:
  hosts:
    store: store.yourdomain.com
    dashboard: dashboard.yourdomain.com
  tls:
    - secretName: urumi-tls
      hosts: [store.yourdomain.com, dashboard.yourdomain.com]
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod

wordpress:
  replicaCount: 1
  resources: {requests: {cpu: 500m, memory: 512Mi}, limits: {cpu: 1000m, memory: 1Gi}}
mariadb:
  storage: 20Gi
postgres:
  storage: 10Gi
```

### 3.3 TLS (optional, strong polish)

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.0/cert-manager.yaml
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata: {name: letsencrypt-prod}
spec: {acme: {server: https://acme-v02.api.letsencrypt.org/directory, email: you@domain.com, privateKeySecretRef: {name: letsencrypt-prod}, solvers: [{http01: {ingress: {class: nginx}}}]}}
EOF
```

---

## 4. Deploy / Upgrade / Rollback

```bash
# local
helm upgrade --install urumi ./helm -n urumi --create-namespace -f helm/values-local.yaml --atomic --timeout 5m

# prod
helm upgrade --install urumi ./helm -n urumi --create-namespace -f helm/values-prod.yaml --atomic --timeout 5m

# secrets (never committed)
kubectl create secret generic gateway-secrets -n urumi \
  --from-literal=FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
  --from-literal=DATABASE_URL=postgresql+asyncpg://urumi:pass@postgres:5432/urumi \
  --from-literal=OPENAI_API_KEY=sk-... \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic woo-secrets -n urumi \
  --from-literal=WOO_URL=http://wordpress:80 \
  --from-literal=WOO_CONSUMER_KEY=ck_xxx \
  --from-literal=WOO_CONSUMER_SECRET=cs_xxx \
  --dry-run=client -o yaml | kubectl apply -f -

# rollback
helm rollback urumi 1 -n urumi
helm history urumi -n urumi

# upgrade image
helm upgrade urumi ./helm -n urumi -f values-local.yaml --set gateway.image.tag=v2
```

---

## 5. What Runs Where (namespaces, secrets, volumes, ingress)

| Component | Kind | Service | PVC | Secret | Public? |
|---|---|---|---|---|---|
| WordPress | Deployment 1× | ClusterIP 80 | wp-content 5Gi RWO | `wordpress-secret` | Yes (via Ingress `store.<domain>`) |
| MariaDB | StatefulSet 1× | ClusterIP 3306 | wp-data 5Gi RWO (volumeClaimTemplates) | `mariadb-secret` | No |
| Postgres | StatefulSet 1× | ClusterIP 5432 | pg-data 5Gi RWO | `pg-secret` | No |
| Woo-MCP | Deployment 1× | ClusterIP 8000 | — | `woo-secrets` | **No** (only gateway via NP) |
| Gateway | Deployment 1×(local)/2×(prod) | ClusterIP 8000 | — | `gateway-secrets` | Yes (via Ingress `dashboard.<domain>/api` + `/mcp`) |
| Dashboard | Deployment 1× (nginx:alpine) | ClusterIP 80 | — | — | Yes (via Ingress `dashboard.<domain>/`) |
| Extra MCPs | Deployment each | ClusterIP | — | optional | No |

**Ingress (templates/ingress.yaml):**

```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: urumi
  annotations:
    {{- toYaml .Values.ingress.annotations | nindent 4 }}
spec:
  ingressClassName: {{ .Values.global.ingressClass }}
  {{- if .Values.global.tlsEnabled }}
  tls:
    - hosts: [{{ .Values.ingress.hosts.store }}, {{ .Values.ingress.hosts.dashboard }}]
      secretName: {{ .Values.ingress.tls.secretName }}
  {{- end }}
  rules:
  - host: {{ .Values.ingress.hosts.store }}
    http: {paths: [{path: /, pathType: Prefix, backend: {service: {name: wordpress, port: {number: 80}}}}]}
  - host: {{ .Values.ingress.hosts.dashboard }}
    http:
      paths:
      - {path: /api, pathType: Prefix, backend: {service: {name: gateway, port: {number: 8000}}}}
      - {path: /mcp, pathType: Prefix, backend: {service: {name: gateway, port: {number: 8000}}}}
      - {path: /, pathType: Prefix, backend: {service: {name: dashboard, port: {number: 80}}}}
{{- end }}
```

---

## 6. Probes & Resources (every workload)

```yaml
# WordPress
startupProbe: {httpGet: {path: /, port: 80}, periodSeconds: 5, failureThreshold: 30}
livenessProbe: {httpGet: {path: /wp-login.php, port: 80}, periodSeconds: 15, failureThreshold: 3, initialDelaySeconds: 60}
readinessProbe: {httpGet: {path: /wp-login.php, port: 80}, periodSeconds: 5, failureThreshold: 2, initialDelaySeconds: 30}
resources: {requests: {cpu: 200m, memory: 256Mi}, limits: {cpu: 500m, memory: 512Mi}}

# MariaDB
livenessProbe: {exec: {command: [healthcheck.sh, --connect, --innodb_initialized]}, periodSeconds: 10}
readinessProbe: {exec: {command: [mysqladmin, ping, -h, 127.0.0.1]}, periodSeconds: 5}
resources: {requests: {cpu: 200m, memory: 256Mi}, limits: {cpu: 500m, memory: 512Mi}}

# Woo-MCP / Gateway / Dashboard
livenessProbe: {httpGet: {path: /healthz, port: 8000}, periodSeconds: 10}
readinessProbe: {httpGet: {path: /readyz, port: 8000}, periodSeconds: 5}
resources: {requests: {cpu: 100m, memory: 128Mi}, limits: {cpu: 300m, memory: 256Mi}} # woo-mcp
# gateway: 200m/256Mi -> 500m/512Mi
```

**Why startupProbe for WordPress:** WP cold start (plugin install) can exceed liveness timeout.

---

## 7. Secrets & No Hardcoding

- **Helm templates use `lookup` or `required` without defaults:**
  ```yaml
  env:
  - name: FERNET_KEY
    valueFrom: {secretKeyRef: {name: gateway-secrets, key: FERNET_KEY}}
  ```
- **Never put `ck_xxx` in values.yaml.** Values have `secrets.create: false` and docs say `kubectl create secret ...`.
- **Hashed API keys:** plain key never stored; only `argon2id` hash in PG.
- **`.gitignore`:** `.env`, `*.key`, `secrets.yaml`.

---

## 8. NetworkPolicy (deny-by-default + explicit allows)

```yaml
# default-deny
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: default-deny}
spec: {podSelector: {}, policyTypes: [Ingress, Egress]}
---
# allow ingress-nginx -> gateway/dashboard/wordpress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-ingress-to-public}
spec:
  podSelector: {matchLabels: {tier: public}}
  policyTypes: [Ingress]
  ingress:
  - from: [{namespaceSelector: {matchLabels: {name: ingress-nginx}}}]
    ports: [{port: 80},{port: 8000}]
---
# allow gateway -> woo-mcp (only gateway)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-gateway-to-woo-mcp}
spec:
  podSelector: {matchLabels: {app: woo-mcp}}
  policyTypes: [Ingress]
  ingress:
  - from: [{podSelector: {matchLabels: {app: gateway}}}]
    ports: [{port: 8000}]
---
# allow wordpress -> mariadb
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-wordpress-to-mariadb}
spec:
  podSelector: {matchLabels: {app: mariadb}}
  ingress: [{from: [{podSelector: {matchLabels: {app: wordpress}}}], ports: [{port: 3306}]}]
```
- Enforce: woo-mcp never gets Ingress traffic; audit by `kubectl get networkpolicy`.

---

## 9. Persistent Storage

```yaml
# pvc-wordpress.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: wp-content}
spec:
  storageClassName: {{ .Values.global.storageClass }}
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: 5Gi}}
# mariadb: volumeClaimTemplates in StatefulSet
# postgres: same
```

- `values-local.yaml` -> `standard` (Kind) / `local-path` (k3d/k3s).
- `values-prod.yaml` -> `local-path` or `longhorn` with `reclaimPolicy: Retain`, `allowVolumeExpansion: true`.

---

## 10. WP Setup Job (Helm hook)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: wp-setup
  annotations: {"helm.sh/hook": post-install, "helm.sh/hook-weight": "5", "helm.sh/hook-delete-policy": hook-succeeded}
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: wp-cli
        image: wordpress:cli
        command: ["/bin/sh","-c"]
        args:
          - |
            until wp core is-installed --allow-root; do wp core install --allow-root --url=http://{{ .Values.ingress.hosts.store }} --title="Urumi Store" --admin_user=admin --admin_password=admin --admin_email=admin@example.com; sleep 5; done
            wp plugin install woocommerce --activate --allow-root || true
            wp wc tool run install_pages --user=admin --allow-root || true
            # create Consumer Key/Secret and print to Secret (or manual step docs)
      envFrom: [{secretRef: {name: wp-setup-secrets}}]
```

Document manual fallback: `wp shell` / `Woo > Settings > Advanced > REST API > Add Key`.

---

## 11. Public vs Internal (enforcement table for video)

| URL | Public? | Enforcement |
|---|---|---|
| `https://store.<domain>` | Yes | Ingress -> wordpress |
| `https://dashboard.<domain>/` | Yes | Ingress -> dashboard |
| `https://dashboard.<domain>/api/*` | Yes (auth) | Ingress -> gateway |
| `https://dashboard.<domain>/mcp` | Yes (API key) | Ingress -> gateway |
| `http://woo-mcp:8000/mcp` | **No** | ClusterIP + NP `allow-gateway-to-woo-mcp` only |
| `http://mariadb:3306` | No | ClusterIP + NP |
| `http://postgres:5432` | No | ClusterIP + NP |

Show in video: `kubectl get svc` (ClusterIP vs Ingress) + `kubectl get networkpolicy`.
