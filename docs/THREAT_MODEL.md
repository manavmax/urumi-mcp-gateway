
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
