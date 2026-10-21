# EXPLAINER (3-5 lines per component)

One short section per new component: what it does, why this approach, main failure mode, how a request flows.


## scripts/regress-core.sh (Phase 0)
What: automates the core Definition of Done on the local kind cluster with two users: a real storefront COD order via the WooCommerce Store API, tools/list counts for admin and member, the orders question via MCP, revoked-key rejection, disabled-upstream hiding (MCP + chat tool load), kill-an-upstream-pod resilience, audit attribution.
Why: the brief's regression gate after every phase; a phase is not done until this passes.
Main failure mode: a stale image in the kind node (pods keep the old image until restarted) - always `make deploy` (or the image targets + rollout restart) before the gate.
Request flow: bash orchestrator -> in-pod python (scripts/lib/regress_store_order.py in woo-mcp pod, scripts/lib/regress_gw.py in gateway pod, state in /tmp inside the pod, deleted at cleanup). Refuses any kubectl context that does not start with kind-.

## Timezone fallback (gateway + demo-time, ADR-054)
What: the chat system prompt always stamps a concrete local date/time; missing/invalid client tz falls back to gateway.defaultTimezone (values-local: Asia/Kolkata). demo-mcp-time answers get_current_time in demoTime.defaultTimezone when the caller omits one.
Why: "today" in order questions must resolve somewhere concrete; a missing browser tz must not leave the prompt dateless.
Main failure mode: an invalid configured zone surfaces the time tool's normal Unknown-timezone error; the prompt falls back to no stamp only if BOTH client and configured zones are invalid.
Request flow: browser sends tz with the chat body -> route validates with zoneinfo -> build_system_prompt stamps local time (client tz, else configured default) -> model resolves "today" against that stamp.

## gw_mcp/metrics.py + routes/metrics.py (Phase 1)
What: Prometheus exposition (tool_calls_total{server,tool,outcome}, per-server duration histogram, upstream_up gauge, rate_limited_total) at GET /metrics, plus GET /api/metrics (admin-only) computing the dashboard Metrics page from the audit table (24h per-server calls, errors, rate, p50/p95, top failure reasons).
Why: stand-out 8 wants real metrics on the gateway and a Metrics page without requiring a Prometheus server; prometheus_client is the single allowed new dependency.
Main failure mode: scrapers cannot reach /metrics until a NetworkPolicy exception is opened for them (in-cluster only by design); every helper fails safe so metrics can never break a call.
Request flow: tool call -> audit outcome decided -> observe_tool_call mirrors it into counters/histogram; health loop -> set_upstream_up; scrape -> GET /metrics (optional METRICS_BEARER); dashboard -> GET /api/metrics -> audit-table group-bys.

## Audit failure classification (Phase 1)
What: the router wraps upstream failures in UpstreamCallError carrying the safe category token; /mcp and the chat agent write it into audit error_code; chat failures (timeout/upstream) are audited now too.
Why: "what broke" must be answerable from the audit trail (timeout vs connection refused vs http 503 vs auth rejected) without ever storing raw exception text.
Main failure mode: a new transport error shape falls back to `other` until categorize learns it; protocol_error split from invalid_response changes one historical label.
Request flow: proxy_call raises -> classify(exc) -> UpstreamCallError(category) -> route audit + metrics carry the token -> Metrics page groups it.

## auth/rate_limit.py (Phase 2)
What: per-key and per-user calls/minute limits enforced with one atomic Postgres upsert per call (rate_limit_counters: scope + minute + count); admin per-key overrides via PATCH /api/keys/{id}.
Why: the limit must hold across replicas (Phase 4 runs 2), and Postgres is already the shared store — no new infrastructure.
Main failure mode: fixed minute windows let a straddling burst double briefly; a DB outage fails OPEN (calls allowed, warning logged) rather than bricking the gateway.
Request flow: /mcp or chat tool call -> consume_and_check (own short session, atomic upsert, both counters) -> over limit: 429 + Retry-After + audit rate_limited + metric; allowed: routing proceeds.

## gw_mcp/compact.py (Phase 3)
What: compact mode for clients with many tools - tools/list serves gateway__search_tools (keyword ranking over the RBAC-filtered catalogue) and gateway__call_tool (invoke a real tool by full name); the chat agent auto-switches above gateway.compactThreshold.
Why: 300 tools cost ~169 KB of tools/list JSON; two meta tools cost ~1 KB, and every real call still goes through the unchanged permission/routing/audit core.
Main failure mode: one extra LLM round-trip per tool call; meta-in-meta and malformed names are rejected as validation errors; default mode ignores the meta names entirely.
Request flow: X-Gateway-Mode/query selects mode -> tools/list meta defs -> search ranks the cached RBAC-filtered catalogue -> call_tool unwraps to the real name -> assert_call_allowed -> call_tool_routed -> audit row carries the REAL tool name.

## Multi-replica gateway (Phase 4)
What: gateway.replicas (1 prod, 2 local) + PDB (minAvailable 1, only with 2+) + soft anti-affinity; login lockout moved into the login_failures Postgres table; alembic upgrades serialized by a Postgres advisory xact lock.
Why: the gateway is stateless (signed cookies, stateless JSON-RPC /mcp, DB-backed tool cache, Postgres rate limits), so replicas are interchangeable - no sticky sessions needed.
Main failure mode: per-replica LLM cooldowns (a cooldown on replica A does not apply to replica B) and the Recreate rollout strategy; the gateway's own egress policy blocks in-pod probes to its Service VIP (use the ingress).
Request flow: any replica serves any request; failed logins append login_failures rows shared by all replicas; on startup each pod takes the migration advisory lock, waits if another pod is mid-upgrade, then no-ops at head.

## 2026-10-21: provisioner + multi-store (ADR-060)

**What it does.** The provisioner is a separate single-purpose service: it
creates a namespace `store-<slug>` (labeled urumi.io/managed-by=provisioner),
installs the store chart there with the helm CLI baked into its image
(`helm upgrade --install <slug> /charts/store`), and deletes it again on
request. The gateway keeps a `stores` row per storefront and enforces who may
create/delete (per-user max, global max, slug rules); it registers the store's
woo-mcp as an INTERNAL upstream (slug == store slug) once the store is Ready.

**Why this approach.** Cluster work needs cluster power (RBAC, helm); giving
the gateway that power would make the biggest blast radius in the system sit on
the internet-facing service. The provisioner is reachable ONLY from gateway
pods (NetworkPolicy) and only with the shared token; its cluster access is
least-privilege plus a code-level rule that it only ever touches namespaces
labeled urumi.io/managed-by=provisioner.

**Request flow.** Dashboard Stores page -> gateway (role + quota + slug checks)
-> provisioner POST /v1/stores (202, task starts, concurrency gate) -> helm
install of the store chart into store-<slug> -> the gateway's sync loop polls
{phase} and, on Ready, registers the store's woo-mcp as an internal server ->
tools appear as <slug>__list_orders etc. Teardown reverses: DELETING label ->
helm uninstall (PVCs keep-annotated survive mishaps) -> namespace delete, and
the gateway removes the row + registration when the namespace is gone.

**Main failure mode.** Provisioning is SLOW (WordPress + WooCommerce install
hook) and the laptop node is small: timeouts are generous, provisioning is
sequential locally, and a timeout marks the store Failed with a safe reason and
a one-click retry (idempotent helm + kept PVCs make retries cheap).

## 2026-10-21: hosted MCP servers (ADR-062)

**What it does.** An admin pastes a container image (tag or digest required)
plus a port and optional env vars; the provisioner deploys it into its own
hosted-<name> namespace as an MCP server and the gateway registers it as an
internal upstream, so its tools appear as <name>__* like every other upstream.

**Why this approach.** The phase-5 provisioner already owns managed namespaces;
hosting is the same pattern minus helm (four plain objects applied idempotently
via the K8s API). The container is boxed in: non-root, read-only rootfs, no SA
token, capped resources, default-deny network with gateway-only ingress and
DNS-only egress. Env VALUES live in a cluster Secret; the gateway stores only
the names.

**Request flow.** Dashboard form -> gateway (admin-only + image rules) ->
provisioner POST /v1/hosted (applies namespace + objects) -> the gateway's sync
sees the Deployment Available -> registers the upstream -> tools appear.
Deletion reverses it and cascades via the namespace delete.

**Main failure mode.** A bad image (crashes, wrong port, no MCP endpoint) just
never becomes Ready; the row fails after the budget with a safe reason and the
namespace can be deleted. The blast radius of a deliberately malicious image is
documented in THREAT_MODEL (hosted servers section).
