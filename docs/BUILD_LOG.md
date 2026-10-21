# BUILD LOG (bonus-all run)

Append-only evidence: real commands, trimmed real output. Newest sections at the bottom.


## 2026-10-21 Phase 0a/0b — timezone + credential-at-rest verification

### 0a timezone
- gateway: `cd src/gateway && ../../.venv/bin/python -m pytest tests/test_timezone_fallback.py -q` → `........` (8 passed)
- demo-time: `cd src/demo-mcp-time && ../../.venv/bin/python -m pytest tests` → `8 passed` (3 pre-existing blank-optional + 5 new default-timezone)
- Frozen-clock proof in tests: 2026-10-21 18:30 UTC = 2026-10-22 00:00 IST; IST prompt says "22 October 2026", UTC prompt says "21 October 2026".

### 0b credential encryption (already existed — verified, not redone)
- `tests/test_credential_at_rest.py` (3 tests, real router + sqlite): planted secret stored as Fernet ciphertext (`gAAAAAB` prefix, plaintext absent from stored bytes, decrypt round-trips); secret absent from every API response (admin+member: /api/servers, /api/servers/{id}, /api/audit, /api/admin-events, /api/tools, /api/stats); secret never logged over create/update/read flow.
- Live DB inspection (in-pod, token never printed):
  ```
  kubectl exec -n urumi <gateway-pod> -c gateway -- python3 -c "<inspection snippet>"
  slug=time credential=none
  slug=woo credential=none
  slug=notes stored_len=164 plaintext_in_db=False decrypts=True value_matches_secret=True
  ```
- Migration state: encryption shipped WITH the initial schema (alembic 001 creates credential_encrypted LargeBinary); no plaintext rows ever existed; re-encryption on Fernet-key rotation is resync_internal_credentials (ADR-026), pinned by tests/test_internal_credential_resync.py (7 tests).

## 2026-10-21 Phase 0c/0d — nginx well-known, executable bit, verify-llm cookie, regress gate

- dashboard nginx: `location ^~ /.well-known/ { return 404; }` added (SPA fallback no longer answers well-known paths with index.html).
- `git update-index --chmod=+x scripts/create-llm-secret.sh` -> mode 100755 in the index.
- scripts/verify-llm.py: session cookie sent as an explicit Cookie header (works with sessionCookieSecure=true where httpx's jar refuses to send Secure cookies over http).
- scripts/regress-core.sh created (+ scripts/lib/regress_gw.py, scripts/lib/regress_store_order.py); refuses non-kind contexts.
- GATE: `bash scripts/regress-core.sh` (after make helm-local + image rebuilds) -> `REGRESS-CORE: ALL CHECKS PASSED`:
  tools/list admin=13 member=13; storefront order #102 placed (Store API COD) and visible via MCP woo__list_orders; disabled upstream hidden from tools/list AND chat tool load; revoked key -> 401; audit rows attributed (member time row, 4 admin rows); demo-time pod killed: woo+notes stayed 200, dashboard showed Unreachable, time recovered.
- Full suites after the changes: gateway 327 passed; demo-time 8 passed (5 new default-timezone); woo-mcp 21 passed; ruff clean; helm lint local+prod clean.
- Environment quirk: the kind node container lives under the colima docker context (default desktop-linux has no containers). Image build/import used `docker --context colima`. Manav should confirm which context is intended -> docs/REVIEW_NEEDED.md.

## 2026-10-21 Phase 1 — observability (ADR-056)

- New tests: `cd src/gateway && ../../.venv/bin/python -m pytest tests/test_metrics_and_classification.py -q` -> `........` (8 passed). Full suite 335 passed (was 327).
- Live /metrics (in-pod): `GET http://127.0.0.1:8000/metrics` -> 200, exposition carries tool_calls_total / tool_call_duration_seconds / upstream_up / rate_limited_total. External probe: `curl -H "Host: dashboard.127.0.0.1.nip.io" http://localhost/metrics` -> the dashboard SPA HTML (the Ingress has no /metrics route to the gateway; the gateway is never reached).
- Live /api/metrics (admin session, real audit rows):
  ```
  GET /api/metrics -> 200 window: 24
    time: calls=12 errors=3 rate=25.0 p50=36ms p95=10023ms failures=[{'reason': 'timeout', 'count': 3}]
    woo: calls=6 errors=0 rate=0.0 p50=101ms p95=156ms failures=[]
    notes: calls=5 errors=1 rate=20.0 p50=23ms p95=221ms failures=[{'reason': 'permission_denied', 'count': 1}]
  ```
- GATE: make lint clean (ruff + helm lint local+prod), make test rc=0 (335/21/8), deployed to kind (gateway+dashboard rebuilt on the colima context), `bash scripts/regress-core.sh` -> `REGRESS-CORE: ALL CHECKS PASSED`.
- Dashboard: Metrics page built (tsc + vite build clean), admin-only route + nav, reason chips.

## 2026-10-21 Phase 2 — rate limits per key (ADR-057)

- Tests: `cd src/gateway && ../../.venv/bin/python -m pytest tests/test_rate_limits.py -q` -> 7 passed (atomicity under 50 concurrent consumers, per-key default, admin override + validation + permissions, per-user spans keys, chat counts against user, fail-open). Suite: 342 passed.
- Migration ran live on the gateway pod start:
  ```
  Running upgrade 006_chat_uploads -> 007_rate_limits, rate limits per key/user (Phase 2, ADR-057)
  rate_limit_counters columns: ['scope', 'window_start', 'count']
  api_keys.rate_limit_per_minute present: True
  ck_audit_outcome: CHECK ((outcome = ANY (ARRAY['success','upstream_error','permission_denied','timeout','circu...
  ```
- Live end-to-end proof (temp admin key, override 3/min):
  ```
  override set: 3 calls/min
  call statuses: [(200, None), (200, None), (200, None), (429, '26')]
  audit rows with outcome=rate_limited: [('rate_limited', 'rate_limited_key', 1)]
  ```
- Gate: make lint clean, suites green, `bash scripts/regress-core.sh` -> ALL CHECKS PASSED (one initial gate failure was a race between the regress audit check and the 1s audit-queue flush — fixed by polling up to 10s in the regress script; the check is now deterministic).
- Dashboard: admin per-key limit editor on the Members page (Set/clear), rate_limited outcome chip.

## 2026-10-21 Phase 3 — compact mode (ADR-058)

- Tests: `cd src/gateway && ../../.venv/bin/python -m pytest tests/test_compact_mode.py -q` -> 11 passed. Suite: 353 passed. make lint clean, helm lint local+prod clean.
- 300 synthetic tools / 10 fake upstreams (unit, seeded catalogue):
  `TOOLS-LIST SIZE: full=300 tools / 168950 bytes; compact=2 tools / 1087 bytes; ratio=0.006`
- LIVE on kind (real gateway, real key):
  ```
  LIVE tools/list: full=13 tools / 6949 bytes; compact=2 tools / 1087 bytes
  compact tool names: ['gateway__search_tools', 'gateway__call_tool']
  search orders -> ['woo__list_orders']
  call_tool time__get_current_time -> 200 (payload: now_local 07:11:45+05:30, timezone Asia/Kolkata)
  default mode meta call -> 400 Unknown server slug 'gateway' for tool 'gateway__search_tools'
  meta audit rows (gateway ops): [('gateway__search_tools', 'success'), ...]
  last audit row (real tool): time__get_current_time
  ```
- Gate: `bash scripts/regress-core.sh` -> REGRESS-CORE: ALL CHECKS PASSED.
