# BUILD STATE (bonus-all run)

> Survival file for context resets. Update after EVERY meaningful step.
> Branch: `bonus-all` (never push, never touch main). Tags: phase-N-done after each phase.
> Cluster: local kind (`kind-urumi`) ONLY. Never run kubectl/helm without checking
> `kubectl config current-context` starts with `kind-`.
> Full command history + evidence: docs/BUILD_LOG.md. Decisions: docs/DECISIONS.md (ADR-054+).

## Current phase

PHASE 2 (rate limits per key) — in progress

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

## What is next

- PHASE 2 rate limits per key: per API key and per user calls/minute from Helm
  values (rateLimit.perKeyPerMinute default, perUserPerMinute), optional per-key
  override by admin (api_keys.rate_limit_per_minute column + PATCH /api/keys/{id}
  or on create), counters in Postgres with ATOMIC upsert (works across replicas),
  over-limit -> clear MCP error with retry-after seconds + audit outcome
  rate_limited (needs the audit CHECK constraint extended) + metric increment,
  chat calls count against the user. Tests incl. concurrency.

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
