# SYSTEM_DESIGN_AND_TRADEOFFS.md (phases 0-8 delta)

The full system architecture lives in docs/01_ARCHITECTURE.md; the security
trade-offs in docs/07 + docs/THREAT_MODEL.md. This file records the DESIGN and
the ACCEPTED TRADE-OFFS of the phases built in this run (ADR-054..063), so
Manav can defend each of them live.

## Provisioner + multi-store (ADR-060)

**Design.** A separate single-purpose Deployment (own image with the helm CLI +
the store chart baked in, own ServiceAccount, reachable only from gateway pods
via NetworkPolicy + a shared token). The gateway owns the RULES (who may create
what, quotas, slug rules, lifecycle rows); the provisioner owns the CLUSTER
(namespace store-<slug> + `helm upgrade --install` + teardown). Store state is
DERIVED FROM THE CLUSTER (WordPress AND woo-mcp Deployments Available + helm
release deployed) — not from task bookkeeping — so a provisioner restart
resumes cleanly and "Ready" always means "serving". Tool names are
<slug>__*, and the WooCommerce keys stay in the store namespace (the gateway
never sees them). Teardown is a namespace delete behind the DELETING label
(label goes on FIRST: a crash mid-teardown resumes deleting instead of
resurrecting the store).

**Trade-offs accepted.**
- ClusterRole is cluster-scoped: K8s RBAC cannot filter namespaces by label.
  Mitigation: code-level label guard on EVERY operation
  (urumi.io/managed-by=provisioner), adoption-resistant create. Residual: a
  compromised provisioner SA could touch non-store namespaces' listed kinds
  (THREAT_MODEL).
- helm over the K8s API: the provisioner shells out to helm (boring,
  battle-tested) instead of using an SDK — the cost is a bigger image and one
  extra process; the benefit is exact parity with the main chart's install
  semantics.
- Readiness derived from the cluster instead of helm --wait: REQUIRED by the
  hook ordering (wp-setup creates woo-secrets that woo-mcp needs to START —
  the main chart's documented first-install deadlock), at the cost of the
  "ready" definition being ours to maintain.
- Sequential provisioning locally (maxConcurrent=1): the 2-core kind node
  cannot fit two wp-setup hooks; the brief sanctions laptop limits. Prod nodes
  can raise the value.
- Store chart is a manual port of the main chart's store components: image
  repos are FORWARDED from the main release (values-local rewrites them), but
  template drift is possible — noted for review.

## Rate limits (ADR-057)

**Design.** Counters in Postgres (atomic upsert), per-key (admin override) +
per-USER, working across replicas; over-limit -> clear MCP error + Retry-After
+ audit outcome rate_limited + metric.

**Trade-off.** A Postgres round-trip per call (vs in-memory): correctness
across replicas beats the ~1ms cost. No sliding window: fixed 60s buckets,
documented.

## Compact tool mode (ADR-058)

**Design.** Opt-in per client (X-Gateway-Mode: compact); tools/list returns
two meta tools; gateway__call_tool goes through the SAME routing, permissions,
rate-limit, timeout and audit code (audit shows the real tool name). The chat
agent switches automatically above gateway.compactThreshold.

**Trade-off.** Two tool surfaces to keep consistent (default + compact) —
mitigated by one shared call path and the regress gate proving the default
mode byte-identical.

## Observability (ADR-056)

**Design.** prometheus_client /metrics in-cluster only (NetworkPolicy, not
through Ingress, optional bearer); failure reasons classified (timeout /
refused / DNS / TLS / auth / 5xx / protocol / circuit) on server cards and in
audit; the dashboard Metrics page computes per-server aggregates from the
AUDIT TABLE (no Prometheus server to run).

**Trade-off.** Audit-table aggregates are eventually-consistent (async audit
writer) and bounded to the audit retention window — fine for a dashboard;
a real Prometheus scrape is still available in-cluster.

## OAuth (ADR-063)

**Design.** Minimal-correct MCP authorization: RFC 9728/8414 metadata, RFC
7591 dynamic registration (public clients, EXACT-match redirects), code +
PKCE S256 only, RFC 8707 resource binding, opaque 5-min access tokens,
rotating refresh tokens (family revocation on reuse), everything hashed at
rest, tokens map to users (same permissions/rate-limits/audit as API keys).
Browser part = dashboard session + consent page.

**Trade-offs.** Public clients only (no secrets — fine for MCP localhost
clients); no grants-management UI yet (revoke via /oauth/revoke + DB); the
resource URI rides the dashboard host locally (prod: dedicated gateway host);
opaque tokens mean an extra DB read per /mcp call (immediate revocation is
worth it).

## Security posture deltas

- The gateway EGRESS allowlist grew by explicit rules: provisioner (port 9000),
  store woo-mcp (label-based), hosted servers (label-based). Default-deny held
  the whole time — every new upstream class needed its own rule, which is the
  design working.
- Hosted containers: non-root, read-only rootfs, no SA token, caps, gateway-only
  ingress, DNS-only egress. An arbitrary admin image still runs SOMEWHERE —
  documented as the residual (THREAT_MODEL).
- Alembic migrations now verified by post-run DB READS (ADR-061: the runner's
  own success log was proven meaningless).
