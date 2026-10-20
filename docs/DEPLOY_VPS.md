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
| ingress-nginx | controller v1.15.1 (chart 4.15.1) | the exact controller the local kind proof ran against (`registry.k8s.io/ingress-nginx/controller:v1.15.1`); chart 4.15.1 is the chart that ships it (`helm search repo ingress-nginx/ingress-nginx --versions` - the earlier 4.14.x pin here was wrong, chart 4.14.x = controller 1.14.x) |
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

### When your IP changes: update the SSH source (finding (f))

The ssh rule's source is `<owner-ip>/32`. The owner's home IP is not static:
when the router reconnects, ISP changes, or you move networks, SSH starts
timing out and the tunnel in section 5 cannot come up. Update the SG source
(never widen it to 0.0.0.0/0):

```bash
curl -s https://checkip.amazonaws.com    # your CURRENT public IP, e.g. 203.0.113.7
```

- AWS console: EC2 -> Security Groups -> the instance's SG -> Inbound rules ->
  Edit the `ssh` rule: set source to `<new-ip>/32` (this replaces the old /32).
- AWS CLI alternative (find the SG id first with `aws ec2 describe-instances`):

```bash
aws ec2 revoke-security-group-ingress --group-id <sg-id> --protocol tcp --port 22 --cidr <old-ip>/32
aws ec2 authorize-security-group-ingress --group-id <sg-id> --protocol tcp --port 22 --cidr <new-ip>/32
```

Then re-establish the tunnel (section 5). Everything else in the SG stays as-is.

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
the cluster through an SSH tunnel. Use the keep-alive flags: without them the
tunnel dies silently when the network changes (laptop sleep, wifi handover,
hotspot switch) and every kubectl/helm call then fails with connection errors
that look like cluster problems (finding (f), gotcha section 8.1).

```bash
# terminal 1 (leave open while operating the cluster; keep-alives every 30s)
ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -L 6443:127.0.0.1:6443 ops@<ip>
```

`ServerAliveInterval=30` sends a keepalive every 30s (keeps NAT/firewall state
alive) and `ServerAliveCountMax=6` declares the connection dead after ~3 minutes
of no answer, so a dropped tunnel fails fast instead of hanging. When the network
changes, rerun this command; the tunnel is the only path to the API server.

Edit the LOCAL copy `~/kubeconfigs/urumi-vps.yaml`: change
`server: https://127.0.0.1:6443` (the on-node default already points at
127.0.0.1:6443, which is exactly what the tunnel forwards) - it must never list
the public IP, because 6443 is firewalled.

TLS SAN: k3s signs its serving certificate with `127.0.0.1` in the SAN list (that
is why the on-node kubeconfig uses `https://127.0.0.1:6443` and verifies), so the
tunnelled address passes certificate verification with no extra flags. If a
future k3s ever drops that SAN, add `--tls-san 127.0.0.1` and restart k3s - do
NOT work around it with insecure-skip-tls-verify.

### KUBECONFIG discipline - read this before ANY kubectl or helm command

This laptop ALSO runs the local kind cluster (context `kind-urumi`). A bare
`kubectl` or `helm` command reads the default kubeconfig and silently targets
the LOCAL kind cluster, not the VPS. Observed live: `make gateway-admin-password`
reported "no password found in Secret" when the real problem was kubectl failing
to reach the VPS (gotcha (g)). ALWAYS do one of:

- prefix every command: `KUBECONFIG=~/kubeconfigs/urumi-vps.yaml kubectl ...`
  (the prefix propagates into `make` targets too: `KUBECONFIG=~/kubeconfigs/urumi-vps.yaml make ps`)
- or use ONE dedicated terminal tab where `export
  KUBECONFIG=~/kubeconfigs/urumi-vps.yaml` runs first, and never reuse it for
  local kind work.

Before anything destructive, confirm where you are pointing:

```bash
KUBECONFIG=~/kubeconfigs/urumi-vps.yaml kubectl config current-context   # NOT kind-urumi
```

Guard rails: never commit the kubeconfig (add it to .gitignore); the tunnel is
the only path; keep the SSH session closed when not deploying.

## 6. ingress-nginx + cert-manager (pinned charts)

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add jetstack https://charts.jetstack.io
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  -n ingress-nginx --create-namespace \
  --version 4.15.1 \
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
# 0. tunnel + context (section 5). EVERY command below is prefixed with
#    KUBECONFIG=... (or run in the one dedicated tab that exported it first):
#    a bare kubectl/helm targets the local kind cluster.
ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -L 6443:127.0.0.1:6443 ops@<ip>
export KUBECONFIG=~/kubeconfigs/urumi-vps.yaml
kubectl config current-context                   # NOT kind-urumi
kubectl get nodes                                # Ready

# 1. controllers (section 6)
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  -n ingress-nginx --create-namespace --version 4.15.1 \
  --set controller.service.externalTrafficPolicy=Local --wait --timeout 5m
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version v1.21.2 --set crds.enabled=true --wait --timeout 5m

# 2. staging issuer (edit ops@example.com first)
kubectl apply -f deploy/cluster-issuer-staging.yaml

# 3. images: build + push once, note the tag
GHCR_OWNER=<owner> make images-push             # prints <tag> = <appVersion>-<sha>
TAG=<tag>

# 4a. FIRST install: NO --wait and NO --atomic/--rollback-on-failure.
#     Helm runs post-install hooks only after --wait is satisfied, and the
#     wp-setup hook is what creates the woo-secrets Secret that the woo-mcp
#     Deployment needs to become Ready - so a fresh install with --wait waits
#     forever for a pod that cannot start until the hook has run.
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
  --timeout 15m

#    then wait for the hook that bakes WordPress + creates woo-secrets
#    (15m budget; watch it with the second command):
kubectl wait --for=condition=complete job/urumi-wp-setup -n urumi --timeout=15m
kubectl get pods -n urumi                        # all Ready after the hook lands woo-secrets

#    EVERY LATER install/upgrade (the Secret exists now, so waiting works):
#   KUBECONFIG=... helm upgrade urumi ./helm -n urumi -f helm/values-prod.yaml \
#     <same --set flags as above> --timeout 15m --rollback-on-failure --wait
#   (helm 3 spells --rollback-on-failure as --atomic; helm 4 still accepts
#   --atomic with a deprecation warning - finding (e). Or: make helm-prod.)

# 5. LLM key (hidden prompt, stdin only, restarts the gateway itself)
KUBECONFIG=~/kubeconfigs/urumi-vps.yaml scripts/create-llm-secret.sh urumi gateway-llm

# 6. post-install checks (note the KUBECONFIG prefix on every command)
KUBECONFIG=~/kubeconfigs/urumi-vps.yaml kubectl get pods,svc,ingress,pvc -n urumi
KUBECONFIG=~/kubeconfigs/urumi-vps.yaml make verify-store        # wp-setup logs + storefront probe
KUBECONFIG=~/kubeconfigs/urumi-vps.yaml scripts/verify-prod.sh <domain>   # item 5 gate, read-only
KUBECONFIG=~/kubeconfigs/urumi-vps.yaml make gateway-admin-password       # gateway dashboard login
KUBECONFIG=~/kubeconfigs/urumi-vps.yaml make admin-password               # WordPress admin login

# 7. first NetworkPolicy confirmation on the real CNI (section 9), then,
#    once staging certs are green, switch the issuer to letsencrypt-prod and re-run
#    the helm upgrade from step 4 with
#    --set ingress.annotations."cert-manager\.io/cluster-issuer"=letsencrypt-prod
```

`gateway.trustedProxies` is already the k3s pod CIDR (10.42.0.0/16) in
`helm/values-prod.yaml`, with the safety comment in that file: only the ingress
controller can reach the gateway because of the NetworkPolicy, so in-cluster
spoofing of X-Forwarded-For is bounded to the controller (ADR-049).

## 8.1 Gotchas we hit on the first real deploy (2026-10-20, with the exact commands)

Real findings from the first live run, now handled by the chart/docs/scripts.
The narrative version lives in SYSTEM_DESIGN_AND_TRADEOFFS.md ("real deployment
log") and docs/DECISIONS.md ADR-051.

- (b) Fresh install: pods Pending with `Insufficient cpu`. The k3s system pods,
  ingress-nginx and cert-manager already hold part of the 2 vCPU node's
  allocatable cpu, and the previous prod REQUESTS (gateway 250m, wordpress
  300m, mariadb 300m, postgres 300m; chart total 1400m) did not fit alongside
  them. Fixed by lowering REQUESTS only (limits untouched) - now the chart
  default in values-prod.yaml (gateway 100m, wordpress 150m, mariadb 100m,
  postgres 100m, chart total 700m).

```bash
kubectl describe pod -n urumi <pending-pod> | grep -A3 Events   # shows "Insufficient cpu"
kubectl get pods -n urumi -o custom-columns=NAME:.metadata.name,CPU_REQ:.spec.containers[*].resources.requests.cpu
```

- (c) Let's Encrypt HTTP-01 solver pods blocked by the default-deny
  NetworkPolicy: the challenge reached ingress-nginx, nginx got 502 reaching the
  solver pod, the CertificateRequest hung. The chart now ships
  `urumi-allow-acme-solver` (ADR-051). Diagnose with:

```bash
kubectl get pods -n urumi -l acme.cert-manager.io/http01-solver=true
kubectl describe certificaterequest -n urumi    # "Waiting for HTTP-01 challenge"
kubectl get netpol -n urumi                     # urumi-allow-acme-solver must exist
```

  Remember the adoption note in section 9: delete the manually created
  `urumi-allow-acme-solver` right before the first upgrade with this chart.

- (d) One-off Let's Encrypt failure "Error looking up CAA records / networking
  error": transient on the ACME side. Delete the failed CertificateRequest and
  let cert-manager retry; it issued on the next attempt:

```bash
kubectl get certificaterequest -n urumi
kubectl delete certificaterequest <name> -n urumi
```

- (f) SSH tunnel drops when the network changes (wifi handover, sleep). Use the
  keep-alive flags from section 5 and rerun the tunnel after any network change;
  if SSH itself times out, your owner IP changed - update the SG (section 2) and
  redial:

```bash
ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -L 6443:127.0.0.1:6443 ops@<ip>
```

- (g) `make gateway-admin-password` said "no password found in Secret" when the
  real problem was a dead tunnel / wrong context: a bare kubectl targeted the
  local kind cluster. The make target now prints the real kubectl error and a
  hint; run it with the prefix:

```bash
KUBECONFIG=~/kubeconfigs/urumi-vps.yaml make gateway-admin-password
```

```bash
KUBECONFIG=~/kubeconfigs/urumi-vps.yaml make gateway-admin-password
```

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

`make helm-prod` upgrades in place (`--timeout 15m --rollback-on-failure --wait`;
helm 4 spelling - helm 3 uses `--atomic`, auto-detected by the Makefile). The
gateway
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
