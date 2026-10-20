# BUILD STATE (bonus-all run)

> Survival file for context resets. Update after EVERY meaningful step.
> Branch: `bonus-all` (never push, never touch main). Tags: phase-N-done after each phase.
> Cluster: local kind (`kind-urumi`) ONLY. Never run kubectl/helm without checking
> `kubectl config current-context` starts with `kind-`.
> Full command history + evidence: docs/BUILD_LOG.md. Decisions: docs/DECISIONS.md (ADR-054+).

## Current phase

PHASE 0 (gaps and hygiene) — in progress

## What is done

- Branch `bonus-all` created from main @ 8cf8f73.
- BUILD_STATE.md / BUILD_LOG.md / EXPLAINER.md scaffolding created.

## What is next

- Phase 0a: timezone (chat agent system prompt date/time/tz; dashboard sends IANA tz
  validated against zoneinfo, fallback gateway.defaultTimezone default Asia/Kolkata in
  values-local only; "today" resolves in that tz; demo-mcp-time default tz env
  demoTime.defaultTimezone; frozen-clock midnight IST vs UTC tests).
- Phase 0b: VERIFY existing Fernet credential-at-rest encryption (do NOT redo): unit test
  + live DB inspection that credential_encrypted is not plaintext; add test grepping API
  responses + logs for credential leakage. Migration for existing rows (check alembic).
- Phase 0c: dashboard nginx /.well-known/* -> 404; chmod +x scripts/create-llm-secret.sh
  (git update-index --chmod=+x); fix make verify-llm for Secure cookies.
- Phase 0d: scripts/regress-core.sh (core DoD automation on kind, two users).

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
| 0 gaps/hygiene | in progress | - | - |
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
