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
- Environment quirk: the kind node container lives under the colima docker context (default desktop-linux has no containers). Image build/import used `docker --context colima`. RESOLVED: the Makefile now carries `DOCKER_CONTEXT ?= colima` (see docs/DECISIONS.md, 2026-10-25 consolidation section).

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

## 2026-10-21 Phase 4 — scaling to 2 replicas (ADR-059)

- Migration 008 ran on BOTH replicas at the same time (advisory lock): both logged `alembic upgrade head done`; `kubectl get deployment urumi-gateway` -> `2/2`; `kubectl get pdb` -> `urumi-gateway MIN AVAILABLE 1`.
- Replica-deletion probe (host -> ingress -> Service, same key, 25 calls, one replica deleted mid-loop):
  ```
  victim deleted
  SUMMARY ok=25 fail=0
  AUDIT rows=25 successes=25 dupes=0 expected_successes=25
  AUDIT OK: no duplicates, no gaps
  ```
- Chat with 2 replicas: `make verify-llm` -> `=== FAILURES: none ===` (multi-step tool loop, MCP create, SSE, wrong-key error path).
- Login lockout shared: tests/test_login_throttle.py::test_lockout_is_shared_across_replicas (two app instances over one DB: the lockout crossed via replica A is enforced by replica B).
- Gate: make lint clean, make test rc=0 (354 gateway tests), helm lint local+prod clean, values-prod renders replicas: 1 and NO PDB, `bash scripts/regress-core.sh` -> ALL CHECKS PASSED (against 2 replicas).
- Quirk found: in-pod connections to the gateway Service VIP are blocked by the gateway's own default-deny EGRESS allowlist (kindnet DOES enforce NetworkPolicy here); probes run through the ingress instead.

## 2026-10-21 Phase 5 — provisioner + multi-store (ADR-060)

- Tests: `cd src/gateway && ../../.venv/bin/python -m pytest tests -q` -> 373 passed
  (test_stores.py 7 router/sync tests, test_provisioner_units.py 12 slug/label/
  marker/image-forwarding tests). demo-time 8 passed, woo-mcp 21 passed, ruff clean,
  helm lint local+prod+store clean.
- Deploy: `DOCKER_CONTEXT=colima make provisioner-image` (helm 3.16.4 + store chart
  baked at /charts/store), `helm upgrade --install urumi ./helm -n urumi -f
  helm/values-local.yaml` (provisioner.enabled=true only local; base/prod false).
- STORE LIFECYCLE (live, in-pod admin session):
  ```
  POST /api/stores "Gate Alpha"/"Gate Bravo" -> 201 (Provisioning, store-<slug>)
  sync loop -> Ready; internal servers:
    [('gate-alpha','Connected','http://gate-alpha-woo-mcp.store-gate-alpha.svc:8000/mcp'),
     ('gate-bravo','Connected','http://gate-bravo-woo-mcp.store-gate-bravo.svc:8000/mcp')]
  tools/list (MCP, admin key): 29 tools, 16 store tools (gate-alpha__*/gate-bravo__*)
  tools/call gate-alpha__list_orders -> 200 {"orders":[],"count":0}
  tools/call gate-bravo__list_orders -> 200 {"orders":[],"count":0}
  ```
- ISOLATION (scripts/lib/phase5_isolation.sh gate-alpha gate-bravo):
  `ISOLATION: ALL CHECKS PASSED` (5/5): woo-mcp->own WP connect-OK; woo-mcp->other
  WP/mariadb BLOCKED; wordpress->own mariadb connect-OK, other mariadb BLOCKED.
- RECOVERY: store "Gate Charlie" created, provisioner pod force-deleted
  mid-provision (`kubectl delete pod -l app=provisioner --force`), new pod's
  reconcile resumed the install -> `STORE gate-charlie status=Ready`.
- CHAT TWO STORES (scripts/lib/phase5_chat_two_stores.py, STUB LLM 127.0.0.1:9101,
  no real key): real chat_loop ran -> TOOLCALLS ['gate-alpha__list_orders',
  'gate-bravo__list_orders'], final text, AUDIT rows under the REAL tool names
  outcome=success -> `CHAT-TWO-STORES: OK`.
- TEARDOWN: delete gate-charlie -> namespace gone, store row removed, internal
  registration removed, 0 charlie tools, 0 charlie PVs.
- GATE: make lint clean; gateway 373, demo-time 8, woo-mcp 21; helm lint local+prod
  + store clean; `bash scripts/regress-core.sh` -> REGRESS-CORE: ALL CHECKS PASSED
  (one flaky check hardened: the dashboard-status check now polls EVERY dark
  iteration and at recovery - the health loop flips Unreachable within its ~5s
  interval, which the old single-sample check raced).
- Fixes landed during the phase (each live-verified): ADR-061 alembic commit bug;
  store chart wp-setup->WordPress ingress rule; wp-setup API egress on service CIDR
  AND node CIDR; helm hook --timeout (1140s local); per-attempt provisioning budget
  (retry resets the clock); DELETING label first; queued-task != "gone"; redrive =
  uninstall+fresh install (PVCs keep-annotated); store chart API egress; IMAGE_MAX_BYTES
  int coercion; fullnameOverride for deterministic <slug>-* names; image repos
  forwarded from the main release; provisioner memory 768Mi; values-local
  maxConcurrent=1 + lighter main-store requests (2-core node).

## 2026-10-21 Phase 6 — hosted MCP servers (ADR-062)

- Tests: gateway 380 passed (test_hosted.py: disabled-flag 403, admin-only,
  image rules incl. allowlist + :latest, name rules, env values NEVER echoed,
  sync register/remove, provision timeout); provisioner units +3 (validate_image,
  namespace naming, build_objects safety contract: non-root/read-only/no-SA-token/
  capped resources/gateway-only ingress/secret-only env values). ruff + helm lint
  (local, prod, store) clean.
- Deploy: DOCKER_CONTEXT=colima make gateway-image && make provisioner-image;
  helm upgrade --no-hooks; alembic -> 010_hosted_servers (verified by DB read,
  the ADR-061 lesson).
- LIVE time2 (demo-mcp-time image, env DEMO_TOKEN -> hosted Secret):
  ```
  POST /api/hosted {name: time2, image: urumi/demo-mcp-time:0.1.0, port: 8000}
    -> 201 {status: Provisioning, env_names: [DEMO_TOKEN]}   (value NOT echoed)
  provisioner applied hosted-time2: Deployment+Service+Secret+NetworkPolicies
  sync -> Ready; internal upstream http://time2.hosted-time2.svc:8000/mcp
  tools/list -> time2__get_current_time, time2__convert_time
  tools/call time2__get_current_time -> 200 {"now_utc": "2026-10-21T19:31:43..."}
  DELETE /api/hosted/<id> -> namespace gone, registration removed, tools gone
  ```
- Two live-found fixes: gateway EGRESS needed a hosted-servers rule (namespace
  label urumi.io/managed-by=provisioner + app: hosted-mcp; ADR-045 default-deny
  blocks new upstream classes by design) and the upstream URL must end in /mcp
  (a pathless URL POSTs to / -> 405; the sync now self-heals Ready rows).
- GATE: make lint; gateway 380 + demo-time 8 + woo-mcp 21; helm lint local+prod
  + store; `bash scripts/regress-core.sh` -> REGRESS-CORE: ALL CHECKS PASSED.

## 2026-10-21 Phase 7 — OAuth on the gateway (ADR-063)

- Tests: gateway 387 passed (test_oauth.py 7: PKCE S256-only, code replay,
  redirect exact-match, refresh rotation + family reuse revocation, resource
  binding, revocation endpoint, hashes-at-rest); ruff + helm lint clean;
  migration 011_oauth applied (verified by DB read).
- LIVE gate: `bash scripts/phase7-oauth-gate.sh` -> 15/15 PASS:
  ```
  PASS unauthenticated /mcp is 401
  PASS WWW-Authenticate points at the RFC 9728 metadata
  PASS protected-resource metadata served
  PASS authorization-server metadata served
  PASS PKCE S256 only
  PASS dynamic client registration (RFC 7591)
  PASS dashboard login (browser session reuse)
  PASS consent page renders
  PASS consent approve -> 302 with code
  PASS code + state returned to the client
  PASS token exchange (PKCE verified)
  PASS tools/list via OAuth bearer token [tools=29]
  PASS tools/call via OAuth bearer token (audited under the user)
  PASS refresh grants new tokens (rotation) / rotated
  PASS revoke accepted / family revocation kills the access token too
  OAUTH-FULL-FLOW: OK
  ```
- SDK CLIENT: `.venv/bin/python scripts/phase7_sdk_oauth_client.py` (the MCP
  Python SDK's OAuthClientProvider over streamablehttp_client):
  ```
  SDK initialize serverInfo: urumi-gateway 1.0.0
  SDK tools via OAuth: 29
  SDK tools/call: {"now_utc":"2026-10-21T20:49:02...", "timezone":"Asia/Kolkata"...}
  SDK-OAUTH-CLIENT: OK
  ```
- GATE: regress-core (run after the phase 6 deploy, unchanged by phase 7 flags)
  -> REGRESS-CORE: ALL CHECKS PASSED; 387 gateway tests.
- One live-found fix: the token endpoint must COMMIT the token-family
  revocation even when the grant is REJECTED (refresh reuse) - otherwise the
  revocation was rolled back with the 400 response.

## 2026-10-21 Phase 8 — docs + traceability + gate stabilization

- REQUIREMENTS_CHECKLIST.md: all five former NOT DONE stand-outs closed with
  live evidence rows (multi-store, OAuth, search_tools/compact, hosted servers,
  metrics); scaling row updated (Postgres rate limits from phase 2); summary
  now 56 DONE / 2 PARTIAL (both documented with workarounds) / 0 NOT DONE.
- README.md: feature-flag table (provisioner/hosted/oauth + stores caps),
  one-paragraph feature summaries, regress gate, demo script steps 5-8.
- SYSTEM_DESIGN_AND_TRADEOFFS.md (root): NEW - the phases 0-8 design + accepted
  trade-offs (per ADR-054..063) for live defense. (Moved from docs/ to root
  2026-10-25; see docs/DECISIONS.md consolidation section.)
- docs/EXPLAINER.md: provisioner, hosted servers, OAuth sections complete.
- THREAT_MODEL.md (root): hosted-image risk, OAuth redirect/token risks,
  one-member-versus-another. (Moved from docs/ to root 2026-10-25.)
- docs/UPGRADE_ROLLBACK.md: new-components upgrade notes (provisioner image
  bakes the store chart; store/hosted state is cluster state; migration 011
  additive; flag-off->on is a plain upgrade; ADR-061 migration verification).
- Makefile: `deploy` now includes the provisioner image + rollout; new targets
  `make isolation A=.. B=..`, `make oauth-gate`, `make sdk-oauth`.
- docs/ENDPOINT_MATRIX.md: regenerated from the table (29 -> 52 routes); the
  table now covers stores/hosted/oauth (flag-OFF shape, with the flag-ON shape
  pinned by the dedicated test files), /api/metrics, /api/notifications,
  PATCH /api/keys/{id}, POST /api/chat/uploads (422-probe note + real-coverage
  pointer), CSRF-exempt reasons for the OAuth grant endpoints. 20/20 matrix
  tests pass; the seeded throwaway store/hosted rows fix the 422 probes.
- REGRESS-CORE gate stabilization: the kill-window poller now STARTS BEFORE
  the pod delete (was: delete first, then poll - a fast-restarting pod elided
  the whole dark window) and the dashboard-status check samples 4x per dark
  iteration + at recovery (the passive mark commits in the request teardown
  AFTER the failing response is sent - a single sample raced it). 5
  consecutive ALL CHECKS PASSED runs (previously ~50% flaky).
- Full suite: gateway 387 passed; ruff clean; helm lint local+prod+store clean.
