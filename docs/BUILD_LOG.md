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
