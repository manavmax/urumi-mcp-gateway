# BUILD STATE (bonus-all run)

> Survival file for context resets. Update after EVERY meaningful step.
> Branch: `bonus-all` (never push, never touch main). Tags: phase-N-done after each phase.
> Cluster: local kind (`kind-urumi`) ONLY. Never run kubectl/helm without checking
> `kubectl config current-context` starts with `kind-`.
> Full command history + evidence: docs/BUILD_LOG.md. Decisions: docs/DECISIONS.md (ADR-054+).

## Current phase

PHASE 6 (hosted MCP servers) — next; PHASE 5 DONE (not yet tagged)

## What is done

- Branch `bonus-all` created from main @ 8cf8f73; BUILD docs scaffolding created.
- PHASE 0 DONE (tag phase-0-done, commit cf2791b): timezone fallback ADR-054
  (gateway.defaultTimezone / demoTime.defaultTimezone, Asia/Kolkata in values-local,
  frozen-clock midnight tests); credential-at-rest verified (ADR-055: Fernet existed,
  3 new tests + live DB inspection); nginx /.well-known 404; create-llm-secret.sh
  executable bit; verify-llm Secure-cookie fix; scripts/regress-core.sh created and
  PASSING (ALL CHECKS PASSED on kind).
- Images built/imported via `docker --context colima` (kind node lives under colima).

## What is done (phase 1)

- PHASE 1 DONE (ADR-056): failure reasons classified into audit error_code
  (protocol_error split from invalid_response; chat failures audited now too),
  Prometheus /metrics (prometheus_client, in-cluster only, optional
  METRICS_BEARER), GET /api/metrics admin-only audit aggregates, dashboard
  Metrics page + nav (admin). 8 new tests; suite 335. Live: external /metrics
  returns the SPA (gateway never reached); /api/metrics returns real 24h
  aggregates. Gate: regress-core ALL CHECKS PASSED.

## What is done (phase 2)

- PHASE 2 DONE (ADR-057): Postgres-backed per-key + per-user rate limits
  (atomic minute-window upserts, migration 007), admin per-key override
  (PATCH /api/keys/{id} + Members page editor), 429 + Retry-After +
  audit outcome rate_limited + metric, chat tool calls count against the user,
  fail-open on counter failure. 7 new tests; suite 342. Live proof: override 3/min
  -> 3x200 then 429 Retry-After 26s; audit row rate_limited_key.
  Gate: regress-core ALL CHECKS PASSED (audit check now polls for the async flush).

## What is done (phase 3)

- PHASE 3 DONE (ADR-058): compact mode (X-Gateway-Mode / ?mode=compact) with
  gateway__search_tools (keyword ranking, RBAC-filtered) and
  gateway__call_tool (same permission/routing/audit path, REAL tool name in
  audit); chat agent auto-switches above gateway.compactThreshold (default 40,
  0=never); default mode unchanged (meta names fall through to unknown-slug).
  11 new tests; suite 353. Sizes: full 300 tools = 168,950 B vs compact 2 tools
  = 1,087 B. Live verified + regress-core ALL CHECKS PASSED.

## What is done (phase 4)

- PHASE 4 DONE (ADR-059): gateway.replicas (1 prod, 2 local), PDB when 2+,
  soft anti-affinity, stateless (documented), login lockout in Postgres
  (migration 008 login_failures; two-app-instance test proves sharing),
  alembic advisory lock serializes concurrent pod migrations. Evidence: 2/2
  replicas, probe 25/25 calls survived a replica delete, audit 25 rows/0 dupes/
  no gaps, verify-llm FAILURES: none, regress-core ALL CHECKS PASSED.
  Quirk noted: in-pod -> gateway Service VIP is blocked by the gateway's own
  egress allowlist (expected; probes use the ingress).

## What is done (phase 5)

- PHASE 5 DONE (ADR-060, evidence in BUILD_LOG): separate provisioner
  Deployment/image/SA (least-privilege ClusterRole + code-level managed-label
  guard), stores table + Stores page, per-user/global maxima, sequential
  provisioning on the laptop (maxConcurrent=1 local), helm/store chart per store
  (fullnameOverride -> <slug>-* names, images forwarded from the main release),
  cluster-derived readiness (WP AND woo-mcp Available), per-attempt budget with
  retry clock reset, DELETING-label-first teardown, reconcile resume after a
  killed provisioner, per-store NetworkPolicies (isolation 5/5), auto MCP
  registration (<slug>__ tools), clean teardown, chat two-store comparison via
  stub LLM. CRITICAL FIX ADR-061 (alembic advisory-lock commit bug - 008/009 had
  silently been rolled back; migrations now verified by post-run DB reads).
  Gate: make lint, 373 gateway tests, demo-time 8, woo-mcp 21, helm lint
  local+prod+store, regress-core ALL CHECKS PASSED.

## What is next

- PHASE 6 hosted MCP servers (stand-out 5): admin adds a server by container
  image in the dashboard (tag/digest required, registry allowlist, port, env
  vars with secret values), the provisioner (same RBAC pattern) deploys
  Deployment+Service+Secret+NetworkPolicy with resource caps, auto-registers in
  the gateway; test with demo-mcp-time as "time2" then remove cleanly. Flag
  hostedServers.enabled default false.

## Commands to resume

```
cd /Users/manavsharma/Desktop/Urumi_AI
git checkout bonus-all
kubectl config current-context   # must start with kind-
make lint && make test           # regression gates
helm lint ./helm -f helm/values-local.yaml && helm lint ./helm -f helm/values-prod.yaml
make deploy                       # rebuild gateway+dashboard images, import, restart pods
bash scripts/regress-core.sh      # core DoD gate (phase 0d onwards)
cd src/gateway && ../../.venv/bin/python -m pytest tests -q   # unit tests
```

## Phase status

| Phase | Status | Tag | Gate |
|---|---|---|---|
| 0 gaps/hygiene | DONE | phase-0-done | REGRESS-CORE ALL CHECKS PASSED |
| 1 observability | DONE | phase-1-done | REGRESS-CORE ALL CHECKS PASSED |
| 2 rate limits | DONE | phase-2-done | REGRESS-CORE ALL CHECKS PASSED |
| 3 many tools | DONE | phase-3-done | REGRESS-CORE ALL CHECKS PASSED |
| 4 scaling | DONE | phase-4-done | REGRESS-CORE ALL CHECKS PASSED |
| 5 provisioner | DONE | phase-5-done | REGRESS-CORE ALL CHECKS PASSED + isolation 5/5 + recovery + chat-two-stores |
| 6 hosted servers | not started | - | - |
| 7 oauth | not started | - | - |
| 8 docs | not started | - | - |

## Environment facts

- kind cluster `kind-urumi` running, all 8 pods Ready (checked 2026-10-21).
- Context: kind-urumi; namespace urumi; release urumi.
- Gateway tests: `cd src/gateway && ../../.venv/bin/python -m pytest tests -q`
- `.venv` already bootstrapped.
- Dashboard URLs: dashboard.127.0.0.1.nip.io / store.127.0.0.1.nip.io (Host header).
- Admin login: admin@urumi.local; password via `make gateway-admin-password` (never print).
- Stash wip-discovery must NOT be touched; untracked debris files must NOT be deleted.
- ADR numbering continues at ADR-054.
