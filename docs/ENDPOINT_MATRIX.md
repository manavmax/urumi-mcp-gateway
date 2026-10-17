# ENDPOINT MATRIX

Generated from the SAME reviewed table that drives
`src/gateway/tests/endpoint_matrix.py` — do not edit by hand.
Regenerate with: `cd src/gateway && ../../.venv/bin/python -m tests.endpoint_matrix`
(the test `test_doc_matches_table` fails if this file drifts from the table).

Coverage: every OpenAPI route x 7 principals, CSRF (missing/wrong) on every
session-auth mutating route, hostile inputs on every POST/PUT/PATCH, IDOR
cross-user isolation, and the MCP JSON-RPC method/tools matrix with audit
assertions. Live-cluster read-only spot checks: scripts/verify-endpoints.sh.

Not covered here: load/concurrency, the ingress/TLS layer, browser-side CSRF
(the table pins the SERVER-side check), SSE framing beyond status codes.

## Routes x principals

| Method | Path | anonymous | member | admin | deactivated | member key | revoked key | expired key | CSRF | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| GET | `/` | 200 | 200 | 200 | 200 | 200 | 200 | 200 | n/a:read-only | service descriptor, no secrets |
| GET | `/healthz` | 200 | 200 | 200 | 200 | 200 | 200 | 200 | n/a:probe | public probe |
| GET | `/readyz` | 200 | 200 | 200 | 200 | 200 | 200 | 200 | n/a:read-only | DB reachability probe |
| GET | `/mcp` | 405 | 405 | 405 | 405 | 405 | 405 | 405 | n/a:GET-only-envelope | SSE GET unsupported: 405 JSON-RPC envelope for every principal |
| POST | `/mcp` | 401 | 401 | 401 | 401 | 200 | 401 | 401 | n/a:bearer-not-cookie | API-key auth enforced in-handler; deactivated user's key also 401 (verify_api_key checks is_active) |
| POST | `/api/auth/login` | 200 | 200 | 200 | 200 | 200 | 200 | 200 | exempt:no-session-yet | 401 for wrong creds or a deactivated account (dedicated tests) |
| POST | `/api/auth/logout` | 200 | 200 | 200 | 200 | 200 | 200 | 200 | exempt:clears only the caller's own cookie | no server-side state change |
| GET | `/api/me` | 401 | 200 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | session cookie only; a Bearer key does not authenticate /api/* |
| GET | `/api/servers` | 401 | 200 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | members need the server list for the dashboard (masked secrets) |
| GET | `/api/servers/{server_id}` | 401 | 200 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | unknown id -> 404 (dedicated test) |
| GET | `/api/keys` | 401 | 200 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | member sees ONLY own keys; admin sees all |
| GET | `/api/tools` | 401 | 200 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | RBAC-filtered catalog (member deny rules hidden) |
| GET | `/api/audit` | 401 | 200 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | member rows scoped to self even with ?user_id=<other> |
| GET | `/api/audit/export` | 401 | 403 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | admin-only CSV, hard-capped at 5000 rows |
| GET | `/api/alerts` | 401 | 200 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | the 'notifications' surface (alert banner); global, no per-user ownership |
| GET | `/api/stats` | 401 | 200 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | member aggregates scoped to own rows; by_server admin-only |
| GET | `/api/users` | 401 | 403 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | admin-only user list |
| GET | `/api/admin-events` | 401 | 403 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | admin action trail (ADR-034) |
| GET | `/api/permissions` | 401 | 403 | 200 | 401 | 401 | 401 | 401 | n/a:read-only | ADR-033 deny policy |
| PUT | `/api/permissions` | 401 | 403 | 200 | 401 | 401 | 401 | 401 | required | replaces member deny policy; unknown names 422 |
| POST | `/api/users` | 401 | 403 | 201 | 401 | 401 | 401 | 401 | required | admin-only; member is 403 even with a valid CSRF header |
| POST | `/api/servers` | 401 | 403 | 201 | 401 | 401 | 401 | 401 | required | SSRF-validated URL; 400 on bad host |
| PATCH | `/api/servers/{server_id}` | 401 | 403 | 200 | 401 | 401 | 401 | 401 | required | admin-only edit |
| POST | `/api/servers/{server_id}/check` | 401 | 403 | 200 | 401 | 401 | 401 | 401 | required | admin Check-now; rate limited 1/5s; upstream mocked in tests |
| POST | `/api/servers/{server_id}/disable` | 401 | 403 | 200 | 401 | 401 | 401 | 401 | required |  |
| POST | `/api/servers/{server_id}/enable` | 401 | 403 | 200 | 401 | 401 | 401 | 401 | required |  |
| DELETE | `/api/servers/{server_id}` | 401 | 403 | 204 | 401 | 401 | 401 | 401 | required | probe targets a THROWAWAY server row |
| DELETE | `/api/users/{user_id}` | 401 | 403 | 204 | 401 | 401 | 401 | 401 | required | probe targets a THROWAWAY user; self-delete is 400 (dedicated test) |
| POST | `/api/chat/completions` | 401 | 200 | 200 | 401 | 401 | 401 | 401 | required | SSE; CSRF added in the F2 pass (dashboard already sent the header) |
| POST | `/api/keys` | 401 | 201 | 201 | 401 | 401 | 401 | 401 | required | member mints for self; admin may pass user_id |
| DELETE | `/api/keys/{key_id}` | 401 | 200 | 200 | 401 | 401 | 401 | 401 | required | probe revokes member A's OWN key; revoking B's is 403 (IDOR tests) |

Principals: anonymous (no credentials); member/admin = session cookie; deactivated = signed session of an is_active=false user; member key = active Bearer key; revoked/expired = dead Bearer keys. CSRF rows list the server-side behaviour; 'required' means missing or wrong `X-CSRF-Token` is 403. Session routes never accept Bearer keys; /mcp never accepts session cookies.

## CSRF-exempt mutations (reviewed)

- POST `/api/auth/login` — pre-session: no authenticated state to abuse; wrong-creds are rate-shaped by the admin-event trail
- POST `/api/auth/logout` — clears only the caller's own cookie; no server state changes
- POST `/mcp` — Bearer-key auth, not cookie auth: a forged cross-site request cannot attach the Authorization header

## Hostile input contract (every POST/PUT/PATCH)

Cases: empty body, wrong types, oversize string (120k), SQL-looking string, extra fields, unicode/control characters.

- NEVER 5xx, never a stack trace, never a secret in any response body (asserted for every case).
- Routes with validated body models must answer 4xx for: empty body, wrong types, oversize strings, SQL-looking slugs/emails (strict set pinned in the test).
- Routes whose body is fully optional ({} on POST /api/keys is a valid mint; bodyless action posts ignore JSON) are held to the never-5xx contract only; a 2xx there is correct behaviour, not a gap.
- SQL-looking strings that pass validation are stored as data through parameterised SQLAlchemy (no injection path); unicode/control characters are preserved as data.

## MCP (POST /mcp, Bearer key)

| Case | Expected |
| --- | --- |
| initialize | 200 serverInfo urumi-gateway |
| notifications/initialized | 202 |
| ping | 200 result {} |
| unknown method | 400 -32601 |
| malformed JSON | 400 -32700 |
| body > 1MB | 413 |
| tools/list admin key / member key | 200 (RBAC-filtered for member) |
| tools/list revoked / expired / deactivated-user key / no token | 401 |
| tools/call valid args (mocked upstream) | 200 result; audit success with the right user |
| tools/call invalid args (tool validation) | 200 isError tool error; audit validation_error |
| tools/call non-object arguments | 400 -32602; audit validation_error |
| tools/call permission denied | 400 unknown-tool error; audit permission_denied |
| tools/call disabled server | 400 validation_error |
| tools/call unreachable upstream | 502 upstream_error |
| tools/call hanging upstream (TaskGroup timeout) | 504 timeout |
| tools/call unknown tool (gateway slug) | 400 validation_error |
| tools/call unknown tool (on upstream) | 200 isError; audit upstream_error |
| malformed JSON-RPC | 400 -32700 |
| oversized arguments > 1MB | 413 |

Audit assertions: rows carry the right user, a stable outcome/error_code, and never argument values.

## Known honest gaps

- The chat agent's INTERNAL audit for a failed tool call (exception paths) writes no row; /mcp audits every outcome. Flagged, out of scope here.
- GET /mcp is a 405 JSON-RPC envelope by design (stateless POST-only gateway).
