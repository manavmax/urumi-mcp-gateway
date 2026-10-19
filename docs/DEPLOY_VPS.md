# DEPLOY_VPS.md - Urumi on a fresh Ubuntu 24.04 VPS

A stranger should be able to follow this end to end. It was written and rehearsed
locally on kind (same chart, same images, same NetworkPolicies); the VPS run itself
is pending and is the one step this document cannot yet prove.

## 1. Versions (pinned) and why

| component | pinned version | why |
|---|---|---|
| k3s | v1.37.x (same minor as the tested kind cluster, kubernetes v1.37.0) | the chart and its NetworkPolicies were rehearsed against the v1.37 API set |
| ingress-nginx | controller v1.15.1 (chart 4.14.x) | the exact controller the local kind proof ran against (`registry.k8s.io/ingress-nginx/controller:v1.15.1`) |
| cert-manager | chart v1.21.2 / app v1.21.2 | installed and exercised on kind (self-signed issuer) before the VPS |
| WordPress core | 6.6 (baked into the wp-cli image, sha1 `6bdc580973c6c5e44c0c6164c348217152874817`) | checksum-verified at image build; no runtime download |
| WooCommerce | 9.4.2 (zip sha256 `002921d59d6de0eedd062db22485b5725ec25f35ea745b355fbff5b51eb45bf0`, recorded in `src/wp-cli/woocommerce-9.4.2.zip.sha256`) | newer 11.x fatals on the WP 6.6 image (ADR: woocommerce.version_pin) |
| chart | urumi-0.1.0, appVersion 1.0.2 | this branch |

Custom images are pulled from GHCR as `ghcr.io/<GHCR_OWNER>/<name>:<tag>` with tags
pinned in `helm/values-prod.yaml` (never `:latest`). If the packages are private,
create the pull Secret once (section 7); the images themselves contain no secrets
(proven by `make smoke-images`).

## 2. VPS bootstrap (fresh Ubuntu 24.04)

Run these as root; everything below assumes a single 2 vCPU / 4 GB node.

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

# firewall: SSH, HTTP, HTTPS only
apt-get update && apt-get install -y ufw
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
ufw --force enable

# 2 GB swap (the 4 GB node needs headroom for build-time spikes)
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# unattended security updates
apt-get install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

## 3. k3s install (pinned, no traefik)

```bash
# Pin the minor to the rehearsed series; check the current v1.37 patch at install
# time. Traefik is DISABLED: the chart ships its own ingress (ingress-nginx).
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="v1.37.2+k3s1" sh -s - \
  server --disable traefik --disable servicelb \
  --write-kubeconfig /etc/rancher/k3s/kubeconfig --write-kubeconfig-mode 600
```

- k3s ships kube-router-style NetworkPolicy enforcement: the chart's default-deny
  NetworkPolicy is ENFORCED on the VPS (it is NOT on kind - kindnet ignores it;
  that is exactly why the blocked-connection probe below is repeated here).
- Flags noted: `--disable traefik` (we bring ingress-nginx instead), `--disable servicelb`
  (ingress-nginx binds the ports via hostPort/daemonset service).

Kubeconfig: copy `/etc/rancher/k3s/kubeconfig` to the laptop and NEVER commit it.
On the laptop: `export KUBECONFIG=~/kubeconfigs/urumi-vps.yaml`.

## 4. ingress-nginx + cert-manager (pinned charts)

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
kubectl apply -f deploy/cluster-issuer-staging.yaml   # edit the email placeholder first
```

## 5. DNS + propagation check

Create A records for `store.<domain>` and `dashboard.<domain>` pointing at the VPS
IPv4. Check propagation from the laptop:

```bash
dig +short store.<domain> @1.1.1.1     # expect the VPS IPv4
dig +short dashboard.<domain> @8.8.8.8
```

## 6. Secrets + install

```bash
# Pin the image tags produced by `make images-push` (tag = <appVersion>-<sha>,
# e.g. 1.0.2-70d640d). Never :latest (ADR-048).
TAG=<tag-from-images-push>
helm upgrade --install urumi ./helm -n urumi --create-namespace \
  -f helm/values-prod.yaml \
  --set gateway.image.tag=$TAG --set dashboard.image.tag=$TAG \
  --set wooMcp.image.tag=$TAG --set demoTime.image.tag=$TAG \
  --set demoNotes.image.tag=$TAG --set storeAssets.image.tag=$TAG \
  --set wordpress.image.tag=<hardened-wp-tag> --set wpSetup.image.tag=<hardened-wp-cli-tag>

# LLM key: hidden prompt, piped via stdin, never a repo file (ADR-050).
scripts/create-llm-secret.sh urumi gateway-llm

# Real domain: --set (or a LOCAL, uncommitted copy of values-prod.yaml)
helm upgrade --install urumi ./helm -n urumi --create-namespace \
  -f helm/values-prod.yaml \
  --set global.domain=<domain> \
  --set ingress.hosts.store=store.<domain> \
  --set ingress.hosts.dashboard=dashboard.<domain> \
  --set ingress.tls[0].secretName=urumi-tls \
  --set ingress.tls[0].hosts[0]=store.<domain> \
  --set ingress.tls[0].hosts[1]=dashboard.<domain> \
  --set gateway.trustedProxies=10.42.0.0/16 \
  --set gateway.corsAllowOrigins=https://dashboard.<domain> \
  --timeout 15m --atomic --wait
```

`gateway.trustedProxies` is the k3s POD CIDR (ingress-nginx pods source from it).
Read docs/DECISIONS.md ADR-049: a pod-suffix trust means in-cluster pods could
spoof X-Forwarded-For; external clients cannot (their real IPs are outside the
pod CIDR), and in-cluster spoofing is an accepted, documented residual.

Post-install checks:

```bash
kubectl get pods,svc,ingress,pvc -n urumi          # all pods Ready
make verify-store                                   # wp-setup logs + storefront probe
scripts/verify-prod.sh <domain>                     # item 5 gate, read-only
```

## 7. Pull secret (only for private packages)

The images are PUBLIC (they contain no secrets - `make smoke-images` proves it), so
this step is optional. To use private packages, create the Secret once from a token
fed via stdin - never commit it:

```bash
kubectl create secret docker-registry ghcr-pull -n urumi \
  --docker-server=ghcr.io --docker-username=<ghcr-user> --docker-password=/dev/stdin
# then add to values: imagePullSecrets: [ghcr-pull]
```

## 8. k3s enforces NetworkPolicy - repeat the blocked-connection probe

kind's CNI (kindnet) does NOT enforce NetworkPolicy, so the local proof is
manifest-level only. k3s DOES enforce it. Repeat the same probe on the VPS:

```bash
# a wp-setup-labelled pod must NOT reach the internet (trimmed NP: no 0.0.0.0/0 rule)
kubectl run egress-probe -n urumi --image=busybox:1.36 --labels="app=wp-setup" \
  --restart=Never --rm -i --restart=Never -- \
  sh -c 'wget -T 6 -q -O /dev/null https://wordpress.org/ && echo REACHED-FAIL || echo BLOCKED-OK'
# Expect: BLOCKED-OK on k3s (enforced); on kind it may print REACHED (kindnet limitation).
```

## 9. Logs, teardown

```bash
kubectl logs -n urumi deploy/urumi-gateway --tail=100
kubectl logs -n urumi -l app=wordpress --tail=100
helm history urumi -n urumi
make helm-prod            # upgrade in place
helm uninstall urumi -n urumi     # teardown (PVCs/kept Secrets stay - see ADR notes)
```

## 10. VPS-only items (cannot be proven on kind)

- real Let's Encrypt issuance (staging first, then prod) and the ACME HTTP-01 path
- public DNS + hostname routing
- ufw only answering on 22/80/443
- NetworkPolicy ENFORCEMENT (kindnet on kind does not enforce; k3s does)
- persistent storage on the real storage class (local-path on k3s)
