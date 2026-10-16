# 11 — Observability (stand-out item 8)

Upstream observability: what the gateway records about every upstream, what each
role sees in the dashboard, and the next-best-action banner. Implemented live
2026-10-16; this document is the contract the code and tests pin.

## 1. Upstream health details

The `servers` table (Alembic `004_servers_health_tracking`) carries, alongside the
existing `status`/`last_error`:

| column                | meaning                                                        |
|-----------------------|----------------------------------------------------------------|
| `last_checked_at`    | last time ANY check touched this upstream (loop, call, Check now) |
| `last_ok_at`         | last time the check or call SUCCEEDED                          |
| `last_latency_ms`    | latency of that most recent outcome                            |
| `last_error_category`| stable category of the last failure (below)                    |

Categories (stored in `last_error_category`; `http_error` always carries the
status code as `http_error:<code>`):

`connection_refused` · `timeout` · `dns_failure` · `tls_error` · `http_error:<code>`
· `invalid_response` · `auth_rejected` (401/403) · `other`

**Nothing raw is ever stored or returned.** `server.last_error` holds ONLY a safe
human label derived from the category (`gw_mcp.categorize.category_label`); raw
exception text, URLs with credentials, headers and tokens are never stored and never
returned. `gw_mcp/health_state.py` is the single writer of these columns.

Every health check and every upstream call outcome updates the row:

- the scheduled health loop (`gw_mcp/health.py`),
- tools/list fan-out (`gw_mcp/aggregator.py` fetch_one),
- every tools/call (`gw_mcp/router.py` call_tool_routed),
- admin "Check now" (`POST /api/servers/{id}/check`).

### Who sees what

- **Admin** (Servers page row): status badge plus a second line, e.g.
  `connection refused, checked 12 s ago, last ok 3 min ago, 41 ms`
  (unknown parts omitted). Fields: `last_checked_at`, `last_ok_at`,
  `last_latency_ms`, `last_error_category`, `last_error` (safe label).
- **Members**: status badge only - no category, no timings, no `last_error`,
  and `credential` stays masked (`null`/`***`), never a value.
- `POST /api/servers/{id}/check`: admin-only (`require_admin`), CSRF-protected,
  rate limited to ONE check per server per 5 seconds (429 afterwards).

## 2. Per-server metrics (admin only)

`GET /api/stats` gains `by_server` for ADMINS ONLY (members never receive the key):
exact SQL aggregates per server over the selected range - calls, error_rate, p50,
p95 (bounded newest-first duration sample, same approach as the headline
percentiles) and a daily sparkline (7 or 14 points over the selected range,
exact SQL counts, empty days filled). Sorted by calls, descending.

## 3. Next-best-action banner

`GET /api/alerts` computes banner state server-side:

- ADMIN payload: one row per alerting enabled server - either Unreachable
  (with category + `unreachable_since`) or error rate over the last hour > 20%
  with at least 5 calls in that hour. Buttons on the dashboard: "Open server"
  (Servers page) and "Check now".
- MEMBER payload: only the affected slugs - "Some tools are temporarily
  unavailable: <slugs>" with no internal reasons.
- No alerts -> empty payload -> no banner. Dismissal is per session
  (sessionStorage) only; a fresh tab shows the banner again.

## 4. Health detection (passive + fast scheduled)

- **Passive**: a tools/list or tools/call that fails at connection level or times
  out marks the server Unreachable IMMEDIATELY (category recorded) - no waiting
  for the next scheduled check.
- **Scheduled**: Helm `gateway.health.intervalSeconds` (default 5) and
  `gateway.health.timeoutSeconds` (default 2), wired to
  `HEALTH_INTERVAL_SECONDS`/`HEALTH_TIMEOUT_SECONDS` env and documented in
  `helm/values.yaml`, `helm/values-local.yaml`, `helm/values-prod.yaml`. While a
  server is Unreachable the loop keeps running, so recovery flips the dashboard
  status back within ~10s of the pod returning.
- A bare `kubectl delete pod` (woo-mcp) is observable: the 5s interval catches the
  down window that the old 15s interval used to miss.

### Live proof (measured, 2026-10-16, kind cluster)

A plain `kubectl delete pod` on the woo-mcp pod (three runs: in-pod API observer +
a Playwright watcher reloading the real dashboard Servers page):

- pod deleted at T; last successful check had been up to 5s earlier; the first
  scheduled check after the pod stopped answering flips the row to **Unreachable**
  within one 5s interval (observed: `connection_refused` immediately, or `timeout`
  with the 2s probe timeout while the pod was mid-termination; the dashboard row
  showed `timeout, checked 0 s ago, last ok 8 s ago, 2.0 s Unreachable`);
- the admin banner appeared in the same interval
  ("woo is unreachable since 8s. Reason: timeout." + Open server / Check now);
- `time` and `notes` tools/call stayed `ok` on every probe throughout the outage;
- the replacement pod came Ready in ~10-15s and the status flipped back to
  **Connected** within ~6-10s of that (total Unreachable window ≈ 12s), well
  inside the 10s-after-recovery target; the banner cleared with the next poll.

## 5. What is deliberately NOT stored

Raw exception text, URLs with credentials, request/response bodies, headers and
tokens never reach the servers table or any API response. The only persisted
error information is the category token plus a fixed human label.
