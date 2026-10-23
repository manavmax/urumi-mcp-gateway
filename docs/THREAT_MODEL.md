## Production exposure of the provisioner ClusterRole (VPS, ADR-060/064/066)

The provisioner is the ONE component with deliberate cluster-wide power, and
the gateway is the only caller. The prod exposure question has two layers:

**The gateway is compromised (the realistic layer).** The attacker holds the
shared provisioner token and reaches the provisioner Service. What they get is
exactly what a legit member flow could do, capped by the platform rules - not
cluster access:
- create/teardown store namespaces (slug-validated, `store-<slug>` named,
  label-guarded) and host images, within the operator-set caps: the private
  prod overlay sets stores.globalMax=3, stores.maxPerUser=1,
  stores.maxConcurrent=1, hostedServers.globalMax=2, so even a hostile admin
  loop cannot farm namespaces unboundedly;
- run store charts (bounded resources: per-namespace ResourceQuota + LimitRange
  render in every store namespace) and hosted images ONLY from the
  configured registry prefixes (hostedServers.allowedRegistries=ghcr.io/<owner>/,
  enforced at apply time; anything else refused);
- the provisioner is NOT reachable from outside the cluster (no Ingress; the
  NetworkPolicy admits gateway pods only) and the gateway exposes no
  cluster-API surface of its own, so browser-side compromise alone reaches
  nothing here.
Residual: a hostile ADMIN can burn the global caps with junk stores/images.
That is an authorized-user abuse problem, not an escalation.

**The provisioner ServiceAccount is compromised (the real blast radius).**
The ClusterRole (rbac-provisioner.yaml) is necessarily cluster-scoped: RBAC
cannot filter namespaces by label. It can list/watch secrets CLUSTER-WIDE and
create/update/delete workload kinds in ANY namespace - only the code-level
label guard (urumi.io/managed-by=provisioner, require_managed on every op)
confines writes, and a compromised SA bypasses code entirely. An attacker at
this layer pivots to reading every Secret (LLM key, WP admin, DB passwords)
and running pods in system namespaces - effectively near-admin. Mitigations:
the pod is reachable ONLY from gateway pods (two-sided NetworkPolicy + shared
token), its egress is API+DNS only, it runs non-root with no extra
capabilities, and the token lives in its SA mount only. Residual accepted for
the single-node VPS: compromise the provisioner pod, lose the cluster. A
namespace-scoped Role per future store namespace + a namespace list cache
would shrink this, at the cost of dynamic RBAC management the demo rejects.

**Hosted servers, production shape:** same controls as the phase-6 posture
(non-root, read-only rootfs, NO SA token, mandatory caps, default-deny with
gateway-only ingress and DNS-only egress) plus the prod allowlist
(ghcr.io/<owner>/ - an attacker with dashboard admin cannot pull an arbitrary
registry image) and globalMax=2. What a malicious hosted image gets: code
execution in a locked-down pod, DNS-resolvable egress only, and its tool
output served to gateway users. It gets NO service-account token, no PVCs, no
cluster API access beyond what default-deny allows (nothing), and it cannot
reach other namespaces' pods (default-deny both directions).

## Per-store TLS: why HTTP-01 and not wildcard (ADR-064)

The VPS DNS host has no API, so DNS-01 is unavailable - and DNS-01 is the ONLY
ACME challenge that can issue wildcard certificates. Consequences: no wildcard
certificate for *.stores.<domain>, therefore NO wildcard secret shared into
store namespaces (that copy would also duplicate a private key across
namespaces). Each store Ingress instead carries its own cert-manager
cluster-issuer annotation (issuer NAME from a value, never hardcoded) and its
own per-store Secret (<slug>-store-tls) issued/renewed automatically by
HTTP-01. The challenge solver pod cert-manager spawns inside every store
namespace would be killed by that namespace's default-deny NetworkPolicy (the
challenge would hang until timeout - observed live in the urumi namespace
before ADR-051), so the store chart renders the same solver allow policy the
main chart has: ingress-nginx may reach ONLY solver pods, ONLY on the solver
port; nothing else can touch them. Trade-off: more Certificate objects and
Let's Encrypt rate limits (5 duplicate certs/week per host, 50/week/domain)
instead of one wildcard; acceptable at stores.globalMax=3, and the per-store
secret never leaves the store namespace (a wildcard secret copied across
namespaces would put the SAME private key in every store namespace).

## Hosted servers (Phase 6, ADR-062)

**Risk: an arbitrary admin-chosen image runs in the cluster.** The hosted-server
feature executes whatever container image an admin names. Controls: tag/digest
required (:latest refused), optional registry allowlist, non-root (uid 1000),
read-only root filesystem, all capabilities dropped, no service-account token,
mandatory resource requests/limits (capped by Helm values), default-deny
NetworkPolicy with ingress ONLY from gateway pods and egress ONLY DNS. The
namespace is provisioner-managed (the label guard confines all provisioner
operations). Residual risk: a malicious image still runs somewhere in the
cluster with its own code - it can attempt in-cluster recon limited by the
default-deny egress (DNS only), and its output is served to gateway users as
MCP tools. Only admins may host; the review question is whether that admin
trust level is acceptable. A gVisor/Kata sandbox or a VM boundary would be the
next hardening step if this left the demo.

## OAuth on the gateway (Phase 7, ADR-063)

**Redirect handling:** redirect_uris are EXACT-match strings (no prefix or
wildcard matching), stored per dynamically registered client; the authorize
endpoint refuses anything else, so an attacker cannot steer codes to their own
listener by crafting a similar URI. Codes are single-use, 10-minute TTL,
PKCE S256 mandatory (authorization-code interception is useless without the
verifier, which never leaves the client machine).
**Token risks:** opaque tokens (no claims to forge), 5-minute access TTL,
refresh rotation with FAMILY revocation on reuse (a stolen refresh token that
is used twice kills the thief's access and the victim's session - the victim
re-authenticates). Tokens are stored only as SHA-256 hashes. Revocation is
immediate via /oauth/revoke.
**Consent:** the user sees the client name, scope and the bound resource and
approves with their dashboard session (CSRF-protected). A malicious MCP client
cannot silently obtain tokens; it needs the user's browser + session.
**One member versus another:** OAuth tokens bind to a USER - the same
role/permission checks, per-user rate limits and audit rows as API keys. A
member's token cannot see another member's stores or keys; internal upstream
lifecycle stays admin-only.
**Residual:** public clients only (no client secrets - acceptable for MCP
localhost clients); no admin UI for listing/revoking a user's OAuth grants yet
(/oauth/revoke + DB are the revocation paths today); the resource URI rides
the dashboard host locally - prod should use a dedicated gateway hostname.
