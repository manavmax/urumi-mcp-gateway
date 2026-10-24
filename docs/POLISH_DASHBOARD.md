# POLISH: DASHBOARD (worktree polish-dashboard)

Run date: 2026-10-24. Branch `polish-dashboard`, 7 commits, nothing pushed.

## Limitation up front: this model cannot view images

The run rules require LOOKING at screenshots. This model (z-ai/glm-5.3) rejects
image input — verified empirically at run start: a generated PNG read through
the file tool returned "Cannot read image (this model does not support image
input)". Per instruction the run paused; the user said "continue", so the work
proceeded with a **programmatic verification battery in place of eyeballs**:

| Script (committed) | What it proves |
|---|---|
| `src/dashboard/scripts/shoot-dashboard.mjs` | every page, dark+light, 1440 (Overview also 390), against the LIVE kind deployment; fails on console/page errors |
| `src/dashboard/scripts/verify-pixels.mjs` | PNG pixel sampling (existing pngjs devDep): dark corners = landing canvas `#040804` (not the old `#14161B`), light corners = light canvas or its designed glow blend, dark/light pairs differ by ~96-99% of pixels (pixelmatch), no blank pages (28-119 distinct colours) |
| `src/dashboard/scripts/verify-dom.mjs` | live DOM in both themes: `data-theme` applied and persists across navigation; computed styles of real elements match tokens (body bg, card bg, stat text, muted labels, chip-ok, primary pill, hero gradient); forbidden helper text absent on every page; required content present; Overview structure (top-tools rows, svgs, range selector, servers table, sparklines) |
| `src/dashboard/scripts/verify-contrast.mjs` | WCAG AA math straight from `tokens.css`: every text pair ≥ 4.5:1 in BOTH themes (body, muted, faint incl. 10-12px, chart axis labels, ok/bad/off badges, primary pills, on-tint pastels, hero gradient worst stop, delta chip); chart bars ≥ 3:1 graphics minimum (dark 3.43:1) |
| `src/dashboard/scripts/verify-overflow.mjs` | no horizontal overflow at 390 on any route, both themes; chart bars + top-tool bars render with non-zero widths |

Final battery output: `ALL PIXEL CHECKS PASSED` / `ALL DOM CHECKS PASSED` /
`ALL CONTRAST CHECKS PASSED (AA)` / `OVERFLOW CHECKS PASSED`, zero console or
page errors beyond the pre-login `/api/me` 401 probe (expected, pre-existing).

**A human should still eyeball the PNGs in `artifacts/dashboard/`** (22 files:
8 pages × 2 themes @1440, overview ×2 @390, login ×2) — the checks above prove
tokens, text, structure and geometry, not aesthetics.

## Item results

### 1. DARK MODE — DONE

`src/dashboard/src/styles/tokens.css` `[data-theme="dark"]` now maps the
landing tokens verbatim (src/landing/styles.css):

- surfaces: bg←canvas `#040804`, surface←`#1A1C19`, sunken fills
  (surface-2/inputs/sidebar/chart track)←surface-alt `#131412`, raised/hover
  fills (tint-soft/primary-tint/row-hover)←surface-raised `#2C2E2B`
- text: `--text`←ink `#E3E5E1`, `--muted`←body `#A8ABA6`,
  `--text-faint`←muted `#8B8E89`
- borders: hairlines `rgba(255,255,255,.05/.10)`
- accents: focus ring, live dot, charts and page-edge glows use the landing
  accent/danger family (teal `#14B8A6` washes, violet, red `#FF5B5B`); the
  hero gradient is accent-deep→deep teal→violet-deep (`#0B3B36→#114C42→#2A2250`)
- light mode untouched; theme choice stays persisted (localStorage `theme`,
  proven by verify-dom across navigations in both themes)

Evidence: pixel checks (dark corners = `#040804`, "not the old dark canvas",
dark/light diff 0.96-0.99), DOM computed-style checks in both themes, contrast
battery. Committed 8b8cbc2 + ffa5678.

### 2. OVERVIEW REDESIGN — DONE

One hierarchy, real data only (hand-written inline SVG, token palette, shared
bento grid):

- KPI row: gradient calls hero (+ window delta pill, arrow now flips for
  "down"), success-rate donut, p95 sparkline, errors tile
- calls-per-day bar chart (hover tooltip, keyboard focusable bars, error
  caps) with a quiet empty state when the window has no calls
- **Top tools** card — new: horizontal call bars with error caps, from a new
  admin-only `top_tools` aggregate in `/api/stats` (exact parameterized SQL
  group-by, top 6 by calls, members never receive it — same scoping as
  by_server; 2 new tests + all 9 existing stats tests pass)
- recent activity, fleet status, account & team (role, members count via the
  existing admin-only `/api/users`, active keys via `/api/keys`)
- admin Servers table kept (calls, error rate, p95, daily sparkline, sorted
  by calls)
- removed: the duplicate half-ring gauge card, the duplicate tools-overview
  card, the static security-posture copy card
- no fake numbers anywhere; empty states are short and honest

Evidence: gateway tests (9/9 in test_stats_scoping.py incl. 2 new), live
`/api/stats` serving real aggregates (103 calls, 75.7% success, p50 25ms,
p95 211ms, top_tools with gate-alpha failures + woo/time/notes), DOM checks.
Commits 55db3c4, 00f9d1b.

### 3. HELPER TEXT — DONE

Removed on every page (Audit scoping banner, pagination offset/limit details,
Metrics "from the audit table / audit_logs via GET /api/metrics" chips and
failure-reason footnote, Stores/Hosted "one namespace per …, tools are
`<slug>__…`" chips + infra paragraphs, Members SHA-256 tile, chat history
"stored in this browser only", ServerForm API-surface footer, Overview
implementation captions). Kept: titles, labels, real validation messages,
short empty-state hints, the key-shown-once notices + revoke warning, the
time-range selector, the FeatureDisabled admin enable hints. Dead `.src` /
`.float-chip` CSS removed. Evidence: forbidden-string assertions across all
8 routes × 2 themes in verify-dom. Commit ee459dd.

### 4. CONTRACTS / AUTH / AA — DONE (with one noted exception)

No API contract changed (top_tools is additive and admin-only); auth, roles,
feature-flag gating (Stores/Hosted show the disabled panel on this
deployment — verified live), key reveal-once and login lockout untouched.
AA: all text pairs pass in both themes (see contrast table above). One
noted exception: LIGHT chart bars measure 1.52:1 against the white card —
pre-existing approved light design, left untouched ("light mode keeps
working"); the same data is available as text (axis labels, tooltips,
aria-labels, per-server table). Dark bars were raised to 3.43:1.

### 5. VERIFY — DONE (with the vision caveat above)

- `npm run build` (tsc -b && vite build): PASS
- `make lint` (helm lint ×2 + ruff): PASS
- `make test` (gateway 120 + woo-mcp 21 + demo-mcp-time 8): PASS
  (worktree bootstraps its venv as a symlink to the checkout venv — PyPI
  downloads timed out from this network; gitignore now matches it)
- real traffic: `src/dashboard/scripts/gen-traffic.mjs` — logs in via the
  dashboard host, creates a real API key, drives ~103 real JSON-RPC
  tools/call through `/mcp` (time, notes, woo orders/products; two schema-
  violating calls are genuine client mistakes classified as validation_error).
  A dead registered server (`gate-alpha`) produced real upstream_error /
  circuit_open rows — real data, and it exercises the error visuals.
- deploy: gateway + dashboard images rebuilt (both changed), imported into
  kind, only those two deployments restarted; no helm upgrade/install;
  kind-urumi context only; no demo-reset; no secrets committed
- screenshots: `artifacts/dashboard/` — 22 PNGs (all pages × dark/light
  @1440, overview @390 both themes, login both themes)

## Fixes made outside the brief (small, evidenced)

- Makefile: `gateway-image`/`dashboard-image` piped `docker save` through a
  contextless `docker exec`, which fails when the kind node lives under the
  colima context (commit 1155b2f)
- `.gitignore`: `.venv` symlink pattern (worktree venv bootstrapping)

## Needs a human eye

1. **Aesthetics pass on the 22 PNGs** — the automated battery cannot judge
   taste; the Overview redesign and dark theme deserve one visual review.
2. Light chart bars (1.52:1 non-text) — decide whether to darken the
   approved light palette or accept the text-availability argument.
3. The delta pill arrow flip (rotate 180° for "down") — verify it reads well.
4. Overview at 390 — grid collapses to one column (CSS media queries kept);
   confirm the top-tools bars and KPI tiles feel right on a phone.

## Decisions

- Extended `/api/stats` with admin-only `top_tools` instead of a new
  endpoint: smaller, same auth/scoping path, additive (no contract change).
  `top_tools` had existed once as a dead audit field and was removed; it is
  now consumed by the Overview card, so the old "dead field" test assertion
  (audit-sub-payload) still holds.
- Verification scripts committed under `src/dashboard/scripts/` (no new
  dependencies — playwright-core/pngjs/pixelmatch are existing devDeps) so
  the evidence chain is reproducible; PNGs stay gitignored in
  `artifacts/dashboard/`.
- Member Overview (OverviewMember) kept its layout; only its helper text was
  trimmed — the admin Overview is the redesign target named by the brief.
