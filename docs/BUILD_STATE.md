# BUILD STATE (bonus-all run)

> Survival file for context resets. Update after EVERY meaningful step.
> Branch: `bonus-all` (never push, never touch main). Tags: phase-N-done after each phase.
> Cluster: local kind (`kind-urumi`) ONLY. Never run kubectl/helm without checking
> `kubectl config current-context` starts with `kind-`.
> Full command history + evidence: docs/BUILD_LOG.md. Decisions: docs/DECISIONS.md (ADR-054+).

## Current phase

PHASE 3 (many tools / compact mode) — in progress

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

## What is next

- PHASE 3 many tools: compact mode selected by X-Gateway-Mode: compact or
  ?mode=compact on /mcp; tools/list returns two meta tools
  gateway__search_tools(query, limit) (keyword ranking over name+description,
  respects role permissions) and gateway__call_tool(name, arguments) routed
  through the SAME permission/rate-limit/timeout/audit code with the real tool
  name in audit; chat agent auto-switches above gateway.compactThreshold;
  test with 300 synthetic tools across 10 fake upstreams; token-size comparison
  in BUILD_LOG.

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
| 1 observability | not started | - | - |
| 2 rate limits | not started | - | - |
| 3 many tools | not started | - | - |
| 4 scaling | not started | - | - |
| 5 provisioner | not started | - | - |
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
