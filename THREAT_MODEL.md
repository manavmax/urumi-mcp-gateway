# Threat Model

Required short note. The long-form talk-track lives in `docs/07_SECURITY_AND_THREAT_MODEL.md`, the decision log in `docs/DECISIONS.md`.

## Assets and attackers

Assets: upstream credentials (Woo consumer key/secret, store namespace keys), gateway API keys, OAuth tokens, the Postgres DB (users, keys, servers, audit), WordPress content, and the LLM key. Attackers: a malicious member (a valid authenticated user), a malicious upstream or hosted image, an external SSRF probe, and (accepted for a single-node demo) a compromised provisioner pod.

## Shared upstream credentials

A member never sees an upstream credential. `GET /api/servers` masks it, credentials are Fernet-encrypted in Postgres, and they are injected server-side at proxy time only: the gateway terminates the client's auth and originates the upstream call with the stored credential. What a member CAN do with a credential they never see is exactly what the per-tool permission table allows on that server: call its tools, see tool output. They cannot extract the secret, call the upstream directly with it, or use it from another tenant's context. Every call is audited under the caller's identity, so abuse is visible and revocable (revoke the key, disable the server, or deny the tool).

## Why client tokens are not passed through

Two separate auth domains: gateway user keys (`Authorization: Bearer <user key>`, stored as argon2id/sha for lookup) and upstream credentials (`Authorization: Bearer <upstream token>` for hosted/external upstreams, or Woo key/secret for woo-mcp). The gateway terminates client auth and originates upstream auth; it never forwards the incoming `Authorization` header. Consequences: a compromised upstream cannot learn any user key, rotating a user key does not touch upstream credentials, and rotating a credential does not revoke users. OAuth access tokens (Phase 7) bind to the same user identity and pass through the same checks as API keys.

## Per-role tool permissions (ADR-033)

Deny rules live in the `tool_permissions` table (role, server_slug, tool_name NULL = whole server) and are enforced by one core (`gw_mcp/permissions.py`) used by listing and calling, on `/mcp` and in the chat agent. What a member cannot do: call a tool an admin denied (rejected before any upstream contact, standard unknown-tool error, no existence leak), see it in `tools/list`, or reach it through a prompt injection in chat (the agent routes through the same check). Every denial writes an audit row with outcome `permission_denied` under the caller's identity.

Default-allow risks, documented and accepted for the demo: (1) with an empty deny table members can call write tools, so the demo policy must be applied live via the Permissions panel; (2) a tool that appears on an upstream after the policy was written is allowed by default until an admin denies it, because the policy names tools, not allowlists. Mitigations: every call is audited, admins can restrict at any time, `make demo-reset CONFIRM=yes` clears rules, and the chat agent refuses tools absent from the filtered list.

## Malicious tool descriptions and output

Tool descriptions and tool output are untrusted data. Mitigations: the system prompt states tool output is data, not instructions; output is sanitized and truncated (20k chars, control characters and `SYSTEM:` markers stripped); descriptions render as text, never markdown; each tool carries a per-server `[slug]` prefix for attribution; the LLM's tool choice is re-checked against the caller's filtered tool list and the permission check before any routing; an admin can disable a bad server at any time.

## What one member can do to another

- Key theft: keys are shown once, stored for argon2id/sha lookup, so a DB dump yields hashes, not keys. `/mcp` authenticates with the Bearer key, not the session cookie.
- Impersonation: the acting user is derived from the validated key or session, never from the request payload; chat resolves the session to a user server-side.
- DoS: per-key and per-user rate limits (Postgres counters, ADR-057), a per-server semaphore and per-server circuit breaker isolate a spammer to their own key and target server. RBAC: a member cannot list other members' keys, users, or admin events.
- OAuth (Phase 7): tokens bind to a user with the same permission, rate-limit and audit path as API keys; one member's token cannot see another member's stores or keys.

## SSRF guard

Admin-supplied upstream URLs are validated at write time (no userinfo, https, private/loopback/link-local/CGNAT ranges and metadata hosts blocked, `127.0.0.1`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16`, `100.64/10`, `::1`, `fc00::/7`, `fe80::/10`, metadata hosts) and re-validated at connect time by resolving DNS and checking every A/AAAA answer, including decimal/hex `inet_aton` forms and hostnames that resolve private. Redirects are never followed (one shared client factory with `follow_redirects=False`). Pinned by `src/gateway/tests/test_ssrf_guard.py`.

## Default-deny NetworkPolicies

Every namespace carries a default-deny ingress/egress policy and explicit allow rules: woo-mcp accepts traffic only from the gateway; MariaDB accepts only WordPress; the provisioner admits only gateway pods on its own port; hosted containers admit only the gateway and may egress only DNS; the gateway's egress is public 443 (the LLM provider) plus the explicit rules for the provisioner, store woo-mcp and hosted servers, with RFC1918 and metadata ranges excluded. Enforcement is real locally (kindnet) and was proven by control tests: no policy connects, default-deny blocks, the allow rule unblocks, an off-label pod is blocked; the same probe is repeated on the VPS as a live confirmation of the k3s CNI.

## Hosted servers and the registry allowlist (ADR-062, Phase 6)

The hosted-server feature runs whatever container image an admin names, so the controls are: tag or digest required (`:latest` refused), registry allowlist (`hostedServers.allowedRegistries`, prefix match with a hard `/` boundary; entries are normalised for trailing slashes, ADR-090), non-root uid 1000, read-only root filesystem, all capabilities dropped, no service-account token, mandatory resource requests/limits capped by Helm values, default-deny NetworkPolicy with ingress only from gateway pods and egress only DNS. In prod the allowlist is pinned to `ghcr.io/<owner>` and `hostedServers.globalMax` caps the count, so even a hostile admin cannot pull an arbitrary registry image or farm namespaces.

Residual, stated plainly: a malicious hosted image still executes its own code somewhere in the cluster. It gets DNS-only egress and its tool output is served to gateway users, but no SA token, no PVCs, no cluster API access beyond what default-deny allows, and it cannot reach other namespaces (default-deny both directions). A gVisor/Kata sandbox or a VM boundary would be the next hardening step if this left the demo.

## The provisioner's ClusterRole: stated residual risk (ADR-060/064/066)

The provisioner is the one component with deliberate cluster-wide power, and the gateway is its only caller. Two layers:

- Gateway compromised: the attacker holds the shared provisioner token and reaches the provisioner Service. They get exactly what a legitimate member flow could do, capped by the operator-set caps (store and hosted namespace creation, images only from the configured registry prefixes, per-namespace ResourceQuota and LimitRange). The provisioner is not reachable from outside the cluster (no Ingress, NetworkPolicy admits gateway pods only) and the gateway exposes no cluster-API surface of its own.
- Provisioner ServiceAccount compromised: this is the real blast radius. The ClusterRole is necessarily cluster-scoped (RBAC cannot filter namespaces by label): it can list/watch secrets cluster-wide and create/update/delete workload kinds in any namespace. Only the code-level label guard (`urumi.io/managed-by=provisioner`, asserted before every operation) confines writes, and a compromised ServiceAccount bypasses code entirely: an attacker at this layer can read Secrets in every namespace (LLM key, DB passwords) and run pods in system namespaces, effectively near-admin. Mitigations: the pod is reachable only from gateway pods (two-sided NetworkPolicy plus shared token), egress is API+DNS only, it runs non-root with no extra capabilities, and the token lives only in its SA mount.

Accepted for the single-node VPS: compromise the provisioner pod, lose the cluster. A namespace-scoped Role per future store namespace plus a namespace list cache would shrink this at the cost of dynamic RBAC management the demo rejects. Even a hostile ADMIN can only burn the global caps (stores.globalMax, hostedServers.globalMax, maxPerUser, maxConcurrent, registry allowlist); that is authorized-user abuse, not escalation.

## OAuth (ADR-063)

Redirect URIs are exact-match strings per dynamically registered client; the authorize endpoint refuses anything else, so codes cannot be steered to a lookalike URI. Authorization codes are single-use, 10-minute TTL, with PKCE S256 mandatory. Tokens are opaque, 5-minute access TTL, refresh rotation with family revocation on reuse (a replayed refresh token kills the thief's access and the victim's session; the victim re-authenticates), stored only as SHA-256 hashes, revocable immediately via `/oauth/revoke`. Consent shows the client name, scope and bound resource and rides the dashboard session (CSRF-protected); a malicious MCP client needs the user's browser and session. Tokens bind to a user, so the same role, permission, rate-limit and audit checks apply. Residuals: public clients only (no client secrets; acceptable for MCP localhost clients), no grants-management UI yet, and the resource URI rides the dashboard host locally (prod should use a dedicated gateway hostname).

## Per-store TLS (ADR-064)

The VPS DNS host has no API, so DNS-01 (and therefore wildcard certificates) is unavailable. Each store Ingress carries its own cert-manager cluster-issuer annotation (issuer name from a value) and its own per-store Secret, so a private key is never shared across namespaces. Because store namespaces are default-deny, the store chart renders the ACME solver allow policy; the trade-off is more Certificate objects and Let's Encrypt rate limits, acceptable at stores.globalMax=3.

## Hardening posture (ADR-041..047)

- Non-root everywhere with an explicit uid (gateway/woo-mcp/demo 1000, dashboard 101, postgres 70, mariadb 999, wordpress/wp-setup 33), all capabilities dropped, no privilege escalation, seccomp RuntimeDefault. The only root container is the throwaway probe pod that verify scripts create and delete.
- One dedicated ServiceAccount per workload, token automount off everywhere except the wp-setup hook (secrets-only Role, lifetime of the ~2 minute hook).
- Read-only root filesystem for gateway, dashboard, woo-mcp, demo servers and postgres; documented exceptions (wordpress, mariadb, wp-setup) still run non-root with no capabilities.
- Login lockout per username and per client IP (5 failures/300s, 429, audited); per-replica in-memory counter, a documented residual.
- Session cookie HttpOnly + SameSite=lax, Secure in prod; CSP (no inline scripts), nosniff, no-referrer, frame-ancestors 'none' on dashboard nginx and gateway API.
- Pod-log secret leak fixed: Apache's `%u` logged the Woo consumer key for Basic-auth REST calls; the hardened image drops it and the log scan reports zero key-shaped strings.

## Chat image uploads (ADR-035)

Uploads are decided by magic bytes only (png/jpeg/webp; SVG, GIF and polyglot files rejected before decode), capped at 5 MB and 4096 px per side with a pixel-count bomb guard checked before decode, then re-encoded with Pillow so no EXIF/GPS or appended payload survives. Storage is owner-bound for 15 minutes, one successful attach deletes the row, filenames are generated server-side, and audit rows never contain image bytes. Text extracted in images is treated as user-typed data at the same trust boundary; every text countermeasure still applies. Data egress: chat text and attached images go to the same configured LLM provider over public 443; uploads are never sent to Woo as raw bytes.

## Admin action trail (ADR-034)

`admin_events` records admin dashboard actions in the same transaction as the action itself (a failed action rolls both back). It never records credentials, raw keys (only `prefix...last4`), or request bodies; failed logins store only the attempted email and reason, rate-capped. Members get 403 on the endpoint. `make demo-reset CONFIRM=yes` truncates it along with `audit_logs`.

## What remains (documented, not hidden)

- Gateway egress stays open to public 443 (minus RFC1918/metadata) because the LLM provider's IP is not knowable in advance; the only open egress in the chart.
- The LLM provider sees chat text and images. No on-prem model option in this design.
- Rate limit and lockout counters are per replica (in-memory); a shared store is the scaling path.
- readOnlyRootFilesystem stays false for wordpress, mariadb and wp-setup (they write their own image fs; non-root and no caps still hold).
- The provisioner ClusterRole is cluster-scoped; see the stated residual above.
- Hosted servers run admin-chosen images; see the stated residual above.
