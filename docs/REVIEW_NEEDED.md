# REVIEW NEEDED (Manav)

Anything security or architecture related to confirm. Newest last.

- 2026-10-21 (env quirk): the local kind node container runs under the **colima**
  docker context; the default docker context is `desktop-linux` (Docker Desktop)
  and shows no containers. All image build/import in this run used
  `docker --context colima`. Confirm which context should be the default, or
  whether the Makefile image targets should gain a DOCKER_CONTEXT variable.
- 2026-10-21 (ADR-054): chat "today" now resolves in `gateway.defaultTimezone`
  (Asia/Kolkata in values-local) when the browser sends no valid timezone. The
  stamp may therefore disagree with the real browser zone when the browser
  refuses to send one - confirm Asia/Kolkata is the wanted demo default and that
  values-prod should stay UTC (it is unset there today).
- 2026-10-21 (regress-core): the throwaway regress member/key material lives in
  /tmp/urumi-regress/state.json INSIDE the gateway pod for the duration of a
  regress run (deleted at cleanup, keys belong to a user the cleanup deletes).
  Acceptable ephemeral handling, but confirm you are happy with the pattern
  before it is reused by later phases.
- 2026-10-21 (ADR-056, /metrics protection): GET /metrics is in-cluster-only (default-deny NetworkPolicy + no Ingress route; proven live) and UNAUTHENTICATED by default; an optional METRICS_BEARER token can be put in the gateway-secrets Secret. Confirm whether you want a token set, and remember a future Prometheus scraper needs its own NetworkPolicy exception (none is rendered today because no Prometheus server is deployed).
- 2026-10-21 (ADR-056, audit classification): `protocol_error` was split out of `invalid_response` for unparseable upstream JSON-RPC responses, and CHAT tool-call failures (timeout/upstream) are now audited where they previously vanished. Confirm the audit semantics change is what you want shown in demos.
- 2026-10-21 (ADR-059, prod replicas): values-prod keeps gateway.replicas=1 as the brief dictates ("1 in values-prod unless Manav changes it"). The PDB only renders with 2+ replicas, so prod has none today. Confirm whether the VPS should run 2.
- 2026-10-21 (ADR-059, per-replica LLM cooldowns): the chat model-fallback cooldowns remain per-replica (a cooldown taken on one replica does not bind the other). Bounded residual; confirm it is acceptable, or ask for a Postgres-backed cooldown in a later pass.
- 2026-10-21 (kind enforces NetworkPolicy): in-pod calls to the gateway Service VIP are dropped by the gateway's own default-deny egress allowlist (kindnet policy controller). This is correct security-wise but surprises in-pod tooling; all live probes now go through the ingress. Confirm you are happy with this posture.
- 2026-10-21 (ADR-061, CRITICAL migration bug fixed): the ADR-059 advisory-lock
  SELECT ran BEFORE alembic's `context.begin_transaction()`, which autobegan a
  transaction; alembic recorded the connection as already-in-transaction and
  therefore NEVER committed (nullcontext), so the connection close ROLLED BACK
  every migration while still logging "alembic upgrade head done". Migration 008
  (login_failures) was silently LOST in phase 4's live run - phase 4's "migrations
  ran on both replicas" evidence was pod-log-only and over-claimed; the live DB
  stayed at 007 until phase 5 hit `column servers.internal does not exist`.
  Fixed in alembic/env.py (lock inside the migration transaction + explicit
  commit); verified live: version=009_stores, login_failures+stores tables exist.
  Please re-check any phase-4 conclusion that assumed 008 was applied live (login
  lockout was fail-open in that window because the table did not exist).
- 2026-10-21 (ADR-060, store chart convergence): the store chart's wp-setup hook
  is post-install and CREATES the woo-secrets Secret that woo-mcp needs to
  START, so the provisioner installs with NO --wait/--atomic (the main chart's
  documented first-install gotcha) and derives readiness from the cluster
  instead (WordPress AND woo-mcp Deployments Available). Confirm you accept
  cluster-derived readiness instead of helm --wait as the store "Ready" signal.
- 2026-10-21 (ADR-060, provisioner RBAC): the ClusterRole is cluster-scoped
  (K8s RBAC cannot filter namespaces by label); the mitigation is code-level
  label guards (urumi.io/managed-by=provisioner asserted before every
  operation, adoption-resistant create). The write rule also covers the kinds
  helm needs inside store-<slug> namespaces only, but RBAC cannot ENFORCE the
  namespace restriction - a compromised provisioner SA could touch any
  namespace's listed kinds. Confirm this residual is acceptable for the demo
  (it is documented in THREAT_MODEL.md).
- 2026-10-21 (ADR-062, hosted images): hostedServers.enabled is FALSE in base and
  prod; the local demo turned it ON. An admin-hosted image is arbitrary code in
  the cluster (boxed: non-root, read-only rootfs, no SA token, capped resources,
  gateway-only ingress, DNS-only egress) - confirm the residual in
  THREAT_MODEL.md "Hosted servers" is acceptable before ever enabling in prod.
- 2026-10-21 (ADR-063, OAuth prod readiness): oauth.enabled is FALSE in base and
  prod; the local demo turned it ON with the resource URI riding the DASHBOARD
  host (http://dashboard.127.0.0.1.nip.io/mcp). Prod should use a dedicated
  gateway hostname + TLS before enabling; there is no grants-management UI yet
  (revocation = /oauth/revoke + the oauth_tokens table).
- 2026-10-21 (stores on the VPS): stores.baseDomain defaults to localhost; prod
  needs a WILDCARD DNS record + wildcard TLS for <slug>.<baseDomain> before
  enabling the provisioner there, and stores.maxConcurrent=2 default assumes a
  bigger node (local runs 1).
- 2026-10-21 (regress-core kill-window flake): stabilized (poller starts before
  the pod delete; dashboard status sampled 4x/iteration + at recovery); 5+ green
  runs. If it flakes again, the remaining race is the pod recovering faster than
  one health interval - widen the dark window with a slower image or scale the
  deployment to 0 briefly.
