# DEPLOY_VPS.md - Urumi on the real server (AWS EC2, Ubuntu 24.04, k3s)

A stranger should be able to follow this end to end against the REAL server. The
chart, images and NetworkPolicies were rehearsed locally on kind; the local
NetworkPolicy proof is a real datapath test (not manifest-level, see section 9),
and the VPS run itself is the one step this document cannot yet prove.

Target server: AWS EC2 m7i-flex.large (2 vCPU, 8 GB RAM, x86_64), Ubuntu 24.04
LTS, region ap-southeast-2, Elastic IP attached. k3s v1.36.5+k3s1 is ALREADY
installed on it (section 4) - do not reinstall or upgrade it as part of a deploy.

## 1. Versions (pinned) and why

| component | pinned version | why |
|---|---|---|
| k3s | v1.36.5+k3s1 (ALREADY installed on the server) | pinned to the installed minor; the chart's objects (apps/v1, batch/v1, networking.k8s.io/v1) are identical in the 1.36 API set |
| ingress-nginx | controller v1.15.1 (chart 4.14.x) | the exact controller the local kind proof ran against (`registry.k8s.io/ingress-nginx/controller:v1.15.1`) |
| cert-manager | chart v1.21.2 / app v1.21.2 | installed and exercised on kind (self-signed issuer) before the VPS |
| WordPress core | 6.6 (baked into the wp-cli image, sha1 `6bdc580973c6c5e44c0c6164c348217152874817`) | checksum-verified at image build; no runtime download |
| WooCommerce | 9.4.2 (zip sha256 `002921d59d6de0eedd062db22485b5725ec25f35ea745b355fbff5b51eb45bf0`, recorded in `src/wp-cli/woocommerce-9.4.2.zip.sha256`) | newer 11.x fatals on the WP 6.6 image (ADR: woocommerce.version_pin) |
| chart | urumi-0.1.0, appVersion 1.0.2 | this branch |

Custom images are pulled from GHCR as `ghcr.io/<GHCR_OWNER>/<name>:<tag>` with tags
pinned in `helm/values-prod.yaml` (never `:latest`). If the packages are private,
create the pull Secret once (section 8); the images themselves contain no secrets
(proven by `make smoke-images`).

## 2. AWS account and network (one-time, before the first deploy)

The AWS security group IS the firewall. There is deliberately NO ufw on the
instance: k3s' own docs advise against host firewalls (ufw/firewalld) because they
fight iptables rules installed by kube-proxy and the CNI. The SG is the only
packet filter that matters.

| SG rule | direction | source | port | why |
|---|---|---|---|---|
| ssh | ingress | `<owner-ip>/32` ONLY | 22 | admin access from the owner's IP alone |
| http | ingress | `0.0.0.0/0` + `::/0` | 80 | ACME HTTP-01 + http->https redirect |
| https | ingress | `0.0.0.0/0` + `::/0` | 443 | public store, dashboard, gateway API |
| all | egress | `0.0.0.0/0` | all | image pulls, LLM provider, ACME |

6443 is NOT open to the internet: kubectl/helm reach the cluster over an SSH
tunnel (section 5). Nothing else is needed inbound.

Instance hardening checklist (one-time):

- Elastic IP allocated and associated, so the DNS A records survive reboots.
- IMDS: hop limit 1, IMDSv2 only (tokens required, response hop limit 1). The
  chart's SSRF guard also blocks 169.254.0.0/16 at the app layer (THREAT_MODEL.md).
- NO IAM instance role attached to the EC2 instance: the node needs no AWS API
  access, so a compromised pod has no AWS credentials to steal.
- Termination protection enabled on the instance.
- AWS Budgets alert on the account (threshold + forecast alerts) so a forgotten
  resource cannot bill silently.
- Ubuntu 24.04 LTS with unattended security updates (`unattended-upgrades`,
  already active by default on 24.04 cloud images).

## 3. SSH bootstrap (one-time; already done on the real server)

Run as root once; everything later runs as `ops`:

```bash
# non-root sudo user + SSH key login
adduser ops && usermod -aG sudo ops
mkdir -p /home/ops/.ssh && cp /root/.ssh/authorized_keys /home/ops/.ssh/authorized_keys
chown -R ops:ops /home/ops/.ssh && chmod 700 /home/ops/.ssh && chmod 600 /home/ops/.ssh/authorized_keys
passwd -l root   # root password lock (after the key is confirmed working)

# disable password authentication over SSH
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?KbdInteractiveAuthentication.*/KbdAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh
```

No swap setup: the node has 8 GB RAM and the workloads fit their limits; k3s
runs fine with the Ubuntu-default swap state (swap is NOT a requirement here).

## 4. k3s (ALREADY installed - verify, do not reinstall)

The server was bootstrapped with the standard stable-channel installer and is at
v1.36.5+k3s1. For reproducibility, the exact command that produced it is:

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_CHANNEL=stable sh -s - \
  --disable traefik --write-kubeconfig-mode 600
```

Pinned equivalent (same result, explicit version):

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="v1.36.5+k3s1" sh -s - \
  --disable traefik --write-kubeconfig-mode 600
```

On the server, verify and note the facts the chart needs:

```bash
kubectl get nodes                                  # Ready, v1.36.5+k3s1
ip -4 addr show | grep inet                        # note the node IP (EC2 private, e.g. 172.31.x.x)
kubectl -n kube-system get ds                      # (no CNI ds: k3s ships its own netpol agent)
```

- Traefik is DISABLED: the chart ships its own ingress (ingress-nginx). ServiceLB
  (klipper-lb) is PRESENT in this install and binds 80/443 on the node for the
  ingress-nginx LoadBalancer Service - do not disable it.
- NetworkPolicy is ENFORCED by k3s (kube-router's netpol controller), and it was
  also proven ENFORCED on the kind rehearsal cluster (kindnet): a control test
  showed a client connect with no policy, get BLOCKED under default-deny, and
  connect again under an allow rule, while an off-label pod stayed blocked
  (section 9). The probe in section 9 is repeated on the VPS anyway as a live
  confirmation on the real CNI.
- k3s defaults used by the chart values: pod CIDR 10.42.0.0/16, service CIDR
  10.43.0.0/16, node IP in the VPC range (172.31.0.0/16 on the default VPC).
  `helm/values-prod.yaml` sets `global.nodeCIDR` to that VPC range - confirm it
  contains the node IP you noted above and `--set` the real one if it differs.

Kubeconfig lives at `/etc/rancher/k3s/k3s.yaml` with mode 600. Copy it to the
laptop over scp and NEVER commit it (it is a cluster-admin credential):

```bash
scp ops@<ip>:/etc/rancher/k3s/k3s.yaml ~/kubeconfigs/urumi-vps.yaml
```

## 5. kubectl/helm access from the laptop (SSH tunnel)

The API server port 6443 is closed in the security group, so the laptop talks to
the cluster through an SSH tunnel:

```bash
# terminal 1 (leave open while operating the cluster)
ssh -N -L 6443:127.0.0.1:6443 ops@<ip>
```

Edit the LOCAL copy `~/kubeconfigs/urumi-vps.yaml`: change
`server: https://127.0.0.1:6443` (the on-node default already points at
127.0.0.1:6443, which is exactly what the tunnel forwards) - it must never list
the public IP, because 6443 is firewalled.

TLS SAN: k3s signs its serving certificate with `127.0.0.1` in the SAN list (that
is why the on-node kubeconfig uses `https://127.0.0.1:6443` and verifies), so the
tunnelled address passes certificate verification with no extra flags. If a
future k3s ever drops that SAN, add `--tls-san 127.0.0.1` and restart k3s - do
NOT work around it with insecure-skip-tls-verify.

```bash
export KUBECONFIG=~/kubeconfigs/urumi-vps.yaml
kubectl get nodes    # through the tunnel
```

Guard rails: never commit the kubeconfig (add it to .gitignore); the tunnel is
the only path; keep the SSH session closed when not deploying.

## 6. ingress-nginx + cert-manager (pinned charts)

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add jetstack https://charts.jetstack.io
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  -n ingress-nginx --create-namespace \
  --version 4.14.0 \
  --set controller.service.externalTrafficPolicy=Local \
  --wait --timeout 5m
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version v1.21.2 --set crds.enabled=true --wait --timeout 5m
```

`externalTrafficPolicy=Local` preserves the real client IP for the
trustedProxies chain (ADR-049). With ServiceLB present, confirm the ingress
service bound the node ports:

```bash
kubectl -n ingress-nginx get svc    # EXTERNAL-IP = the node IP (the Elastic IP's private address)
```

Then apply the STAGING issuer first (edit the placeholder email first):

```bash
kubectl apply -f deploy/cluster-issuer-staging.yaml
```

## 7. DNS + propagation check

Create A records for `store.<domain>` and `dashboard.<domain>` pointing at the
Elastic IP. Check propagation from the laptop:

```bash
dig +short store.<domain> @1.1.1.1     # expect the Elastic IP
dig +short dashboard.<domain> @8.8.8.8
```

## 8. Deploy day: the exact order of commands

Placeholders: `<domain>` = the real domain, `<owner>` = the GHCR owner,
`<owner-ip>` = the owner's home IP, `<tag>` = the tag `make images-push` produced.
Run from the repo root on the laptop with `KUBECONFIG` and the tunnel up.

```bash
# 0. tunnel + context (section 5)
ssh -N -L 6443:127.0.0.1:6443 ops@<ip>          # separate terminal, leave open
export KUBECONFIG=~/kubeconfigs/urumi-vps.yaml
kubectl get nodes                               # Ready

# 1. controllers (section 6)
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  -n ingress-nginx --create-namespace --version 4.14.0 \
  --set controller.service.externalTrafficPolicy=Local --wait --timeout 5m
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version v1.21.2 --set crds.enabled=true --wait --timeout 5m

# 2. staging issuer (edit ops@example.com first)
kubectl apply -f deploy/cluster-issuer-staging.yaml

# 3. images: build + push once, note the tag
GHCR_OWNER=<owner> make images-push             # prints <tag> = <appVersion>-<sha>
TAG=<tag>

# 4. install the chart with the real domain + pinned tags
helm upgrade --install urumi ./helm -n urumi --create-namespace \
  -f helm/values-prod.yaml \
  --set global.domain=<domain> \
  --set ingress.hosts.store=store.<domain> \
  --set ingress.hosts.dashboard=dashboard.<domain> \
  --set ingress.tls[0].secretName=urumi-tls \
  --set ingress.tls[0].hosts[0]=store.<domain> \
  --set ingress.tls[0].hosts[1]=dashboard.<domain> \
  --set gateway.image.tag=$TAG --set dashboard.image.tag=$TAG \
  --set wooMcp.image.tag=$TAG --set demoTime.image.tag=$TAG \
  --set demoNotes.image.tag=$TAG --set storeAssets.image.tag=$TAG \
  --set wordpress.image.tag=<hardened-wp-tag> --set wpSetup.image.tag=<hardened-wp-cli-tag> \
  --set gateway.corsAllowOrigins=https://dashboard.<domain> \
  --timeout 15m --atomic --wait

# 5. LLM key (hidden prompt, stdin only, restarts the gateway itself)
scripts/create-llm-secret.sh urumi gateway-llm

# 6. post-install checks
kubectl get pods,svc,ingress,pvc -n urumi       # all pods Ready
make verify-store                               # wp-setup logs + storefront probe
scripts/verify-prod.sh <domain>                 # item 5 gate, read-only

# 7. first NetworkPolicy confirmation on the real CNI (section 9), then,
#    once staging certs are green, switch the issuer to letsencrypt-prod and re-run
#    the helm upgrade from step 4 with
#    --set ingress.annotations."cert-manager\.io/cluster-issuer"=letsencrypt-prod
```

`gateway.trustedProxies` is already the k3s pod CIDR (10.42.0.0/16) in
`helm/values-prod.yaml`, with the safety comment in that file: only the ingress
controller can reach the gateway because of the NetworkPolicy, so in-cluster
spoofing of X-Forwarded-For is bounded to the controller (ADR-049).

## 9. First NetworkPolicy enforcement on k3s (diagnosis guide)

The policies were enforced and probed live on kind, but k3s is a DIFFERENT CNI
(kube-router's netpol controller), so the first k3s bring-up is the first time
 THESE policies meet that enforcement path. If pods hang NotReady or calls fail
right after the first install, work down this checklist:

What the policies MUST allow on k3s (all values-driven in the chart):

1. kubelet probes from the node: readiness/liveness probes originate from the
   node, not a pod. kube-router/kindnet exempt local-node traffic, but if pods
   stick NotReady with `describe` showing probe timeouts, test from a node shell.
2. DNS: `urumi-allow-dns` permits egress to `namespaceSelector
   kubernetes.io/metadata.name=kube-system` + `podSelector k8s-app=kube-dns`.
   k3s CoreDNS carries that label and lives in kube-system (service IP
   10.43.0.10); namespaces carry the metadata.name label automatically.
3. ingress-nginx -> gateway/dashboard/wordpress: `urumi-allow-ingress-to-public`
   matches the controller's namespace via `kubernetes.io/metadata.name:
   ingress-nginx` (the chart installs it exactly there).
4. wp-setup job -> Kubernetes API + mariadb + wordpress: the API ClusterIP
   (10.43.0.1:443 on k3s) is DNAT-ed to `<node-ip>:6443`, so egress must allow
   the NODE CIDR - `global.nodeCIDR` MUST contain the node IP (values-prod
   defaults to the EC2 VPC range 172.31.0.0/16; verify with `ip -4 addr show`).
   The mariadb/wordpress legs are pod-selector rules (CNI-agnostic).
5. gateway -> upstreams (woo-mcp, demo-time, demo-notes, postgres): pod-selector
   rules, no node involvement.
6. ACME HTTP-01 solver pods (ADR-051): the chart's default-deny also covers
   cert-manager's short-lived `cm-acme-http-solver-*` pods (label
   `acme.cert-manager.io/http01-solver=true`, port 8089). The chart now ships
   `urumi-allow-acme-solver`, ingress ONLY from the ingress controller namespace
   on port 8089 (values: `networkPolicy.acmeSolver.port`), rendered when TLS is
   enabled. Without it nginx 502s reaching the solver and the CertificateRequest
   hangs (observed live, gotcha (c) in the deploy log).

ADOPTION (one-time, before the first upgrade that ships this chart): the live
cluster already has a manually created `urumi-allow-acme-solver`. Helm refuses
to adopt a resource it does not manage, so delete it right before that upgrade
(the solver pod only exists while a challenge is in flight, so deleting the
policy between renewals is safe):

```bash
kubectl delete networkpolicy urumi-allow-acme-solver -n urumi
```

Fast diagnosis recipe:

```bash
kubectl -n urumi get netpol                          # the 8+ policies exist
kubectl -n urumi describe netpol urumi-default-deny  # policyTypes ingress+egress, podSelector {}
kubectl describe pod -n urumi <stuck-pod>            # Events: probe failures vs pull failures
# throwaway probe from inside the namespace:
kubectl run np-probe -n urumi --rm -it --image=busybox:1.36 --restart=Never -- \
  sh -c 'nc -z -w3 urumi-postgres 5432 && echo OK || echo BLOCKED; nslookup kubernetes.default.svc'
```

Emergency off-switch (diagnosis tool ONLY, not a fix to leave on):
`helm/values.yaml` exposes `networkPolicy.enabled` (default `true`). Setting it
false and re-running the install removes EVERY policy (denies and allows alike -
there is no half state). Use it only to isolate a suspected netpol outage during
diagnosis, then re-enable immediately (`--set networkPolicy.enabled=true`) and
re-run `scripts/verify-hardening.sh`. A deployment left with policies off is an
unaccepted posture: the default-deny is what bounds every tier.

Repeat the blocked-connection probe on the VPS as the live confirmation:

```bash
# a wp-setup-labelled pod must NOT reach the internet (trimmed NP: no 0.0.0.0/0 rule)
kubectl run egress-probe -n urumi --image=busybox:1.36 --labels="app=wp-setup" \
  --restart=Never --rm -i -- \
  sh -c 'wget -T 6 -q -O /dev/null https://wordpress.org/ && echo REACHED-FAIL || echo BLOCKED-OK'
# Expect: BLOCKED-OK (the same result the kind control test proved for kindnet).
```

## 10. Upgrades and the 6-minute rollback demo

`make helm-prod` upgrades in place (`--timeout 15m --atomic --wait`). The gateway
Deployment ships `gateway.progressDeadlineSeconds: 300` (values-driven), so a
DELIBERATELY bad upgrade rehearsed with `--timeout 6m` fails fast at the 5-minute
deadline and auto-rolls back in about 6 minutes total instead of 10 - rehearsed
with real timing in docs/UPGRADE_ROLLBACK.md section b2 (5:09.84 on kind).

## 11. Logs, teardown

```bash
kubectl logs -n urumi deploy/urumi-gateway --tail=100
kubectl logs -n urumi -l app=wordpress --tail=100
helm history urumi -n urumi
helm uninstall urumi -n urumi     # teardown (PVCs/kept Secrets stay - see ADR notes)
```

## 12. VPS-only items (cannot be proven on kind)

- real Let's Encrypt issuance (staging first, then prod) and the ACME HTTP-01 path
- public DNS + hostname routing on the Elastic IP
- the AWS security group as the only firewall (22 from the owner IP, 80/443 open)
- live NetworkPolicy confirmation on the k3s CNI (section 9; enforcement itself is
  already proven by the kind control test)
- persistent storage on the real storage class (local-path on k3s)
