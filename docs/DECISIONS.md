# Design decisions log (STAGE 0)

Append-only. One entry per decision, newest last.

## 2026-10-14: palette moved from sage green to dusty blue (calm English pastel)

**What changed.** The dashboard palette is now: page `#EEEDE8` warm greige, cards `#FFFFFF`,
sidebar and wells `#F6F5F1`, ink `#1E2430`, muted `#7A8190`, hairline `#E4E2DB`, one primary
dusty blue `#4F6F94` (hover `#425F82`, soft tint `#DCE7F3`), and five accent tints for cards,
chart bars and avatars: butter `#F3E6C4`, blush `#F4DCD8`, lilac `#E4DEF1`, sky `#DCE7F3`,
sand `#EADFCB`. Status badges: Connected mint `#DDEDE4` with text `#2F5D46`, Unreachable blush
`#F4DCD8` with text `#8A3B33`, Disabled grey `#E9E8E3` with text `#6B7280`, always icon plus text.

**Why.** The brief asked for a calm English pastel palette matching the reference screenshots and
for the sage green to be removed. A single dusty blue primary keeps the UI calm at high
information density while giving links, active nav and primary buttons one clear accent.
Measured contrast: primary on white 5.21:1 and white on primary 5.21:1 (AA for normal text),
ink on white 15.55:1, Connected 6.24:1, Unreachable 5.84:1.

**Alternatives considered.**
- Keeping sage green as the primary: rejected by the brief; it also read as "health status" and
  competed with the mint Connected badge.
- Warm terracotta or oxblood primary: closer to the reference art but too heavy for dense data
  tables and for long sessions.
- Multi-hue categorical palette for charts: rejected for calm; charts now use the five accent
  tints plus the primary, with semantic error text colour only for error caps.
- Dark mode token set: still out of scope, listed as a needs-decision item.

**Known trade-off.** Two requested colours measure below 4.5:1 for small text: muted `#7A8190`
is 3.91:1 on white and 3.34:1 on the greige, and Disabled text `#6B7280` on `#E9E8E3` is
3.94:1. They pass AA for large text only. The mockups keep the requested values and flag the
pair; Stage 1 should either darken muted to about `#5F6673` or treat those strings as decorative.

## 2026-10-15: STAGE 0.6, bento pattern with ink primary and controlled gradients

**What changed.** The mockups move to the reference pattern: warm greige canvas `#ECEBE7`, white
borderless cards (radius 24, inner chips 14), layered shadows `0 1px 2px rgba(20,23,28,.04), 0 10px 30px rgba(20,23,28,.05)`,
ink `#14171C` as the only primary (buttons, active nav, segmented active, toggles), muted `#5F6673`,
Disabled badge text `#565D69`, Overview rebuilt as a bento grid (four equal stat tiles with one
gradient hero, wide chart with floating mini-cards, half-ring gauge, my-account card, activity with
accent bars, tools overview, fleet status), greeting page header with a pill search field and a
round ink search button, a floating pill sidebar (72px icon-only, expands to 248px as an overlay on
hover or focus-within with an 80ms intent delay, 20ms label stagger, 150ms collapse delay), a chat
page with a centered gradient-glow empty state, suggestion cards, a wide pill composer with a round
ink send button and a right-hand chat history panel, and a login re-skin on a soft gradient glow.

**Why.** The brief locked logo A, required the pastel bento and floating-pill-sidebar pattern from
the new references (pattern, not content), ink primary actions with gradient reserved for one hero
tile, the gauge or chart fill, the login art, the chat glow and the page-edge glow.

**Gradient options.** `design/mockups/palette-options.html` renders the Overview hero and gauge in
three non-green gradients: A "Dusk" (`#B9C4DD`, `#D9C8DC`, `#EFCBBE`; ink on stops 10.27 / 11.33 /
11.94 to 1), B "Mist" (`#A9BBD3`, `#CFE0EE`, `#F3EAD8`; 9.18 / 13.30 / 15.03), C "Rose sand"
(`#E3BFB8`, `#EADFCB`, `#D5E0EC`; 10.62 / 13.61 / 13.43). A "Dusk" is recommended and ships as the
working default; the final choice is still with the user.

**Contrast.** All pairs now pass AA for normal text: ink on white 17.96:1, muted `#5F6673` on white
5.78:1 and on greige 4.84:1, Disabled `#565D69` on `#E9E8E3` 5.41:1, Connected 6.24:1, Unreachable
5.84:1, white on ink 17.96:1. This closes the two below-threshold pairs flagged in the 0.5 entry.

## 2026-10-15: STAGE 1 slice 1, tokens, shell and shared components

**What changed.** The React dashboard adopts the 0.6 token set (greige `#ECEBE7` canvas, white
borderless cards with radius 24 and layered soft shadows, ink `#14171C` as the only primary,
muted `#5F6673`, Disabled text `#565D69`), the floating pill sidebar as an overlay (72px collapsed,
248px on hover or focus-within, 80ms intent delay, 150ms collapse delay, 20ms label stagger,
instant under reduced motion), a greeting topbar with the pill page search (client-side, reset per
route), a mobile bottom tab bar, the shared Card, StatTile, Badge, StatusBadge, Button, Toggle,
Table, Skeleton, Empty and Error components, the inline SVG icon set with logo A, and the login
page with glow, white card and ink button. Favicon is the logo A knockout variant, ink updated to
`#14171C`.

**Why.** Slice 1 of the approved plan. No UI or animation library was added; icons are inline SVG,
motion is CSS keyframes with the global reduced-motion rule in tokens.css.

**Deviations and notes.**
1. No CLAUDE.md file exists in the repo, so the slice followed the rules in the task prompt.
2. ESLint has no flat config file in src/dashboard (pre-existing), so `npx eslint` exits 2 with a
   configuration error. The dashboard gate is tsc plus vite build; make lint covers helm and ruff.
3. The Overview nav item routes to "/" which still redirects to /servers until slice 2 lands.
4. Nine pre-existing em dashes in page UI strings were replaced with commas, colons or "n/a", and
   one dark-theme hard-coded mint text colour in Members was moved to `var(--ok-text)`.
5. Search field is wired to a shared client-side query context; pages consume it in slices 2 to 4.
6. Greeting name is derived from the real email local part (admin@urumi.local becomes Admin).

**Deferred.** Dark mode: second token set plus prefers-color-scheme. Deferred in STAGE 1 planning;
mockups and app ship light only.

## 2026-10-15: STAGE 1 correction, exact mockup port across all pages

**What changed.** The deployed dashboard was a recolour of the old layouts, not the approved
design. Every page is now an exact DOM and CSS port of design/mockups/*.html, with real data and
the locked STAGE 1 decisions: GET /api/stats (new, admin = all users, member = own calls,
parameterized SQLAlchemy, range day/week/month/14d default 14d) drives the new Overview page,
which is now the default landing at /overview; the audit CSV export (GET /api/audit/export,
admin-only server-side, 5000-row cap, BOM-prefixed, no argument values) is wired to the audit
page button; chat history is browser-only localStorage (last 20 sessions per user, cleared on
sign out). Parity is proven by scripts/parity.mjs (playwright-core + pixelmatch + pngjs devDeps):
geometry and computed styles at 1440x900 with 8px w/h and 12px x/y tolerances, plus a login pixel
diff under 3% at 1440x900 and 390x844 with reduced motion. After-stage screenshots and the parity
report are in artifacts/.

**Why.** The correction requires the mockups to win over the spec and over the old layouts, a
script-proven parity table per page and role, and a single combined report.

**Deviations and notes (all also listed in the STAGE 1 report).**
1. Login logo block is STACKED (mark, wordmark, muted sub beneath, left aligned) per the
   acceptance contract, which supersedes the mockup's inline row. The parity script applies this
   and the named drift classes to the mockup before measuring, and logs it.
2. The login mockup defines .glow-bg CSS but renders no such element, so the port ships exactly
   the three drifting shapes and no background-glow div.
3. overview.html hides .user-menu (display:none), so the Overview header carries only the search
   pill; the account menu lives on the fleet pages' topbar, as their mockups show.
4. Mockups disagree with each other in three places; the port unifies per page where they differ
   and documents it: td padding (servers/members 12px flat, audit 11px 12px), card-title weight
   (overview/chat 650, fleet 750) and stat-num weight (overview 650, members 750). The
   .content max-width (1240 overview/chat, 1280 fleet), gutters, gaps and h1 size are scoped by
   the fam-o / fam-f classes on the shell.
5. Mockup-only chrome not shipped: SAMPLE DATA and Auto-refresh chips, the Motion toggle and
   rm-note, the Admin/Member view switcher (role comes from the session), the skeleton and
   empty-state demo cards, the interactive chart tooltip (bars keep native title tooltips), the
   count-up animation (final values render immediately), and the CSV export button stays
   admin-only in the member view because the endpoint is 403 for members.
6. Members (member view): the mockup still shows the fleet-wide Members tile, but GET /api/users
   is 403 for members, so the live member view hides it and shows Your role instead; this is the
   one parity row that differs by design (reported as DATA, not FAIL).
7. Chat persistence copy: the mockup's NEEDS DECISION note is replaced with the localStorage
   decision text. Key expiry: the create flow sets none, so new keys show "never"; the UI has no
   expiry picker.
8. The audit CSV button is enabled (the mockup has it disabled, NEEDS DECISION) because the
   export endpoint now exists and is tested.
9. Grid hygiene: bento and grid cards get min-width 0 so a long real email cannot widen a
   fractional column; the account email ellipsizes.
10. Overview range: the seg offers Day/Week/Month exactly as the mockup, default Week; the chart
    subtitle follows the selected range (the mockup's 14d subtitle contradicted its own Week
    selection). The API default remains 14d.
11. ESLint still has no flat config (pre-existing); the dashboard gate is tsc plus vite build.
12. Members page head: the mockup's page-head sub ("Invite members, manage roles and API keys.
    Keys are shown once at creation.") is folded into the API keys card title, because the create
    flow is the only place a key is displayed. The Members page head therefore carries no sub.

## 2026-10-15: STAGE 1 polish pass, member-scoped Overview (FIX 1)

**What changed.** Members landing on /overview previously saw the admin page with zeros. /overview
now renders OverviewMember.tsx, which is scoped to the signed-in user: Getting started (three
steps: create an API key, connect an MCP client, make a first call), Connect your client (MCP URL
plus the Authorization header), My activity (my calls, success rate, p95 latency), Calls per day,
Tools I can use, Recent activity, and Try in chat. Nothing is fabricated: every number, the audit
list and the tool list come from GET /api/stats and GET /api/audit filtered to the session user.
The gateway stats route now returns own_api_key_calls, and scripts/parity.mjs gained MEMBER_STRUCTURE
checks for the member page (required sections, no admin-only text, no horizontal overflow at 1440
and 390) because no static mockup exists for it.

**Why.** The member view must be useful without leaking team-wide numbers or other members'
emails, and it must not look like a broken empty admin page.

**Decisions.**
1. "MCP client connected" counts any audit row that carries api_key_id, because POST /mcp
   authenticates with the API key and writes api_key_id, while chat rows are session-based and
   carry none. That makes origin determinable without a new endpoint.
2. The card uses its own bento rows (.activity-row, .ct-row) with the same responsive collapse as
   the admin rows, so the member page reads as one family with the approved admin layout.
3. The admin Overview is unchanged: the polish brief scoped FIX 2 to clutter, and the admin page
   passed parity as approved.
4. Getting started hides itself once all three steps are done, so the card is an empty state that
   disappears rather than dead chrome.
5. The member header search mirrors the admin one and is non-functional by design, so the shell
   is identical across roles.

## 2026-10-15: STAGE 1 polish pass, clutter removal (FIX 2)

**What changed.** Page-level clutter is gone: 10 dev-doc or duplicate lines removed across
Servers (page-head sub), Members (Users card sub, one sentence of the keys helper), Audit
(page-head sub, the Filters note and the Day/Week/Month helper) and Chat (page-head sub, the
composer SSE helper, the history footer). Counts of one-line subs per page after the pass:
Login 0, Servers 0, Chat 0, Members 1, Audit 1 (the Tool calls data readout), admin Overview
unchanged at 5, member Overview 3 (its own data and source subs). Headings, card titles, column
headers and stat labels are untouched.

**Why.** The brief was one page title plus at most one short information-adding line, with
section headings that repeat the title, uppercase eyebrows and dev-doc helper sentences removed.

**Decisions.**
1. The login helper "Use your workspace account to reach the gateway console." is kept: there
   are two separate admin logins (WooCommerce dashboard and this gateway) and the WordPress
   account name is also admin, so the line prevents a predictable wrong-dashboard mistake. It
   also anchors the login pixel diff, so removing it would have moved the accepted baseline.
2. Provenance and scope copy stays: .src chips, the audit CSV button title, the audit scoping
   note-banner, "Keys are shown once at creation." and the revoke warning. The audit page-head
   sub was removed together with its .src chip, which left the audit page with no .src at all,
   so parity now measures .src on the servers and members pages instead of the whole fleet set.
3. The mockups are static and still render the removed lines, so the parity selector specs were
   adjusted (.src and the fleet page-head sub) rather than editing the mockups, which are the
   frozen reference.
4. The removed Members sentence was the expiry dev note; the create flow sets no expiry, so
   the keys table keeps showing "never" and no expiry UI was implied.

## 2026-10-16: per-role tool permissions, member deny rules (ADR-033)

**What changed.** Admins can now restrict which tools the MEMBER role may call. The policy
lives in a new `tool_permissions` table (Alembic migration `003_tool_permissions`): deny
rules of (role, server_slug, tool_name) where tool_name is the EXPOSED name
(`woo__create_product`) or NULL for a whole-server deny, plus created_by/created_at and a
CHECK constraint that only allows role='member'. Admins always have all tools; an empty
table is the default allow-all policy and changes nothing (DoD demo untouched).

Enforcement is ONE function set in the routing core (`gw_mcp/permissions.py`):
`deny_rules_for_role` reads the rules live on every request (no cache that survives a
change), `tool_denied` is the single predicate, `filter_tools_for_user` filters
`tools/list` (external `/mcp`, `GET /api/tools`, and the chat agent's tool load), and
`assert_call_allowed` checks the namespaced exposed name BEFORE routing upstream. A denied
call returns the standard unknown-tool error (no existence leak), never reaches the
upstream, and writes an audit row with outcome `permission_denied` under the caller. The
chat agent additionally audits a forced (prompt-injection) call to a denied tool as
`permission_denied` and streams it with that outcome.

API: `GET /api/permissions` (admin) returns every server with its tools and the
member-denied flag plus a restricted count; `PUT /api/permissions` (admin only,
CSRF-protected, `require_admin` server-side) replaces the member policy wholesale and
validates that every server and tool name exists (422 otherwise). Members get 403.
Dashboard: a Permissions panel on the Servers page (admins only) — tools grouped by
server, Admin column locked on, Member toggle, restricted count, one Save button with a
success state. Members get no permission UI; restricted tools are absent from their
tools/list, Servers page and Overview "Tools I can use". `make demo-reset` clears the
table back to allow-all.

**Why.** Stand-out item 2 of the brief (per-role tool permissions). Security-critical
features get one server-side code path, so both the external MCP client and the chat
agent cannot drift. Deny rules (not allow lists) keep the default policy allow-all so the
Definition of Done (member creates products in chat) passes unchanged.

**Alternatives considered.**
- Per-user rules: rejected; the brief scopes permissions to roles, and per-user rules
  would duplicate the audit/keys ownership model for no demo gain.
- Allow-list per role: rejected as default policy; allow-lists silently break when a new
  upstream tool appears (it would be hidden for members until manually allowed) and the
  brief demands default-allow with the deny policy applied live.
- Caching the deny set: rejected; the table is tiny and read per call, so no invalidation
  bug can survive a policy change (pinned by a test).

**Known trade-offs.** A newly appearing upstream tool is allowed for members by default
(documented in THREAT_MODEL.md); admins must add a deny rule (or deny the whole server)
after registering such an upstream. The deny table is read twice per call path (list +
call) instead of cached — trivial for the demo's row counts. Only role='member' can hold
rules; a future admin-restriction would need a migration (the check constraint).

**Tests first.** `tests/test_tool_permissions.py` (12 tests: default policy, listing
filter for member vs admin, real SDK client over streamable HTTP, denied call rejected
with zero upstream calls + `permission_denied` audit row, policy change on next call,
rule removal restores, PUT 403/CSRF/422, GET shape) and the extended
`test_prompt_injection.py` (chat agent refuses an injected denied tool, zero upstream
calls, audited) were written before the enforcement wiring; run against the
pre-implementation tree they fail (10 failures), with it the full suite is green.

## 2026-10-17: Admin action trail ADR-034

**What changed.** A new append-only `admin_events` table (Alembic migration
`005_admin_events`) records admin actions with actor, target, outcome and non-secret
details: `server.create/update/enable/disable/delete`, `user.invite/delete`,
`key.create/revoke`, `permission.change`, and `login.failed` (attempted email + time
only). The table is the single destination for the question "who did what, when, did it
work".

The **secrecy contract** is enforced in the recorder (`audit/admin_events.py`):
- Server credentials are stored ONLY as `credential_changed: true` or `credential_removed: true`
- API keys appear ONLY as `prefix...last4` plus the owner's user id (never the raw key, never the digest)
- Passwords are NEVER stored (not even a hash)
- Request bodies are NEVER stored
- `login.failed` details are only `{"reason": "invalid_credentials"|"inactive"}`
- `target_ref` is a non-secret reference (slug, email, user id, key prefix+last4)
- All detail dicts are small bounded objects of field names and counts, never free text

**Write model.** `record_admin_event()` only calls `db.add()` into the caller's session.
The route's existing commit lands action + event together; a failure (400/exception)
rolls both back, so a failed action cannot leave a success event behind (pinned by
`test_failed_server_create_no_success_event` in `tests/test_admin_events.py`).
`login.failed` commits its own row because the event IS the completed action; the
rate-limited write prevents a flood of bad logins from flooding the trail.

**login.failed rate limiting.** One source (the attempted email) can write at most
`LOGIN_FAILED_EVENT_LIMIT` (10) rows per `LOGIN_FAILED_WINDOW_SECONDS` (60s). Beyond
that the write is silently dropped. This uses the same in-memory rate-limit pattern
as the per-key MCP limiter.

**No mutation API.** There is deliberately NO POST/PUT/PATCH/DELETE on the trail router:
- All mutation attempts return 405 (confirmed by tests)
- `make demo-reset` is the ONE sanctioned wipe for admin_events (TRUNCATE, same
  documented exception as audit_logs)

**API.** `GET /api/admin-events` (admin only, members get 403) is paginated with
filters by actor (user id or email), action and date range. Actor emails are resolved
in the same query pattern as `GET /api/audit`. The response shape:
```json
{"total": N, "limit": 100, "offset": 0, "events": [
  {"id": 1, "ts": "...", "actor_user_id": "uuid|null", "actor_email": "email|null",
   "action": "server.create", "target_type": "server", "target_ref": "slug",
   "outcome": "success|failure", "details": {}}
]}
```

**Dashboard.** The Audit page (`src/dashboard/src/pages/Audit.tsx`) gains a segmented
control "Tool calls | Admin activity" (admins only; members never see it). The Admin
activity view shows time, actor, action, target and outcome in the same table style
as the tool calls table, with independent pagination. The `listAdminEvents` API method
was added to `src/dashboard/src/lib/api.ts`.

**Tests.** `tests/test_admin_events.py` (24 tests covering: secrecy checks with planted
secret strings that must never appear in any stored/returned byte; one event per action
with correct actor; member 403 on GET; all mutation endpoints 405; rate limit per
source; failed action leaves no success event; pagination; action and actor filters).

**Why.** The brief required an audit trail for admin actions ("who did what"). Separating
it from the per-call `audit_logs` table keeps each table focused: one for tool calls,
one for admin actions. The secrecy contract prevents credential leakage through the
trail. The transactional write model eliminates the class of bug where a success event
exists for a rolled-back action.

**Known trade-offs.** The rate limiter is in-memory (per-process, not shared). On a
multi-worker gateway, each worker has its own limit window. This is the same trade-off
as the per-key MCP rate limiter and is acceptable for the demo. A future Redis-backed
limiter would fix it at the cost of infrastructure complexity. `user.role_change` does
not exist as an API endpoint yet; when it is added, it should call `record_admin_event`
following the same pattern.

## 2026-10-18: F1 dashboard theme is Light and Dark only (System removed)

**What changed.** The dashboard offers exactly two themes: Light and Dark, in the
user menu dropdown and the sidebar rail control. The System option is removed
from `theme.ts`, the pre-paint script in `index.html`, and both controls. The
default when nothing is stored is Light; a stored `system` or any unknown value
is treated as Light. The favicon keeps following the theme (tile from `--ink`,
glyph from `--primary-pill-text`, rebuilt on switch).

**Why.** Owner report on the live build: three theme states tripled the contrast
surface and System made the rendered mode unpredictable in tests and screenshots.
Two explicit modes keep the contrast gate (scripts/contrast.mjs) deterministic.

**Known trade-off.** Users who previously chose System now get Light until they
pick Dark; honouring the OS preference is intentionally dropped for determinism.



## 2026-10-18: FIX PASS F1 - chat threads, notification bell, safe markdown (ADR-036)

**Chat threads (item 4).** One thread per conversation, not one history entry per
message: the dashboard keeps an ACTIVE thread id; sending continues it, "New chat"
or opening the chat page starts a new one, clicking a history row restores the whole
conversation. Threads live in localStorage per user (last 20 threads, title = first
user message, stored message count) - unchanged STAGE 1 storage decision. The client
sends only prior user/assistant text (last 10 turns, 12k char cap); the SERVER now
rejects any other role with 400, so a client cannot inject fake system text or tool
results (enforced in routes/chat.py, tested in tests/test_chat_roles.py). LLM error
turns are shown inline and never stored, so a thread is never titled with an error
string.

**Notification bell (item 6).** GET /api/notifications is computed on the fly from
existing tables (servers, audit_logs, admin_events, api_keys) - no new table. Admins
get fleet items (unreachable servers, failed/denied calls in 24h, revoked keys /
disabled servers); members get ONLY their own failures/denials and their own keys
expiring within 7 days. Max 20 items, newest first. No new table: the bell state is
derived per request. The dot uses a per-user lastSeen timestamp in localStorage
("Mark all read"); the popover closes on Esc/outside click and returns focus to the
bell. Scoping + secrecy are pinned by tests/test_notifications.py.

**Readable replies (item 8).** Assistant text renders through a hand-written SAFE
markdown renderer (src/dashboard/src/lib/markdown.tsx): paragraphs, bold, italic,
inline code, lists, tables and http/https-only links (rel noopener noreferrer,
target _blank). No new dependency, no dangerouslySetInnerHTML, markdown images are
dropped and unsafe schemes stay inert text (unit-tested in scripts/verify-markdown.mjs
with react-dom/server). The chat system prompt pins the order-list format (summary
line + Order/Status/Total/Placed/Items table, draft orders excluded) and the browser
sends its IANA timezone, validated with zoneinfo (fallback UTC), so "today" means the
user's today.

**Why.** The owner reported one history entry per message, raw markdown (**Order
#89**) in replies, a dead bell and wrong "today" in chat answers. Threads stay
client-side per the STAGE 1 localStorage decision; the server-side role restriction
keeps the prompt-injection boundary (only the gateway produces system/tool roles).

## 2026-10-18: F3 image upload reuses the Woo consumer key via a mu-plugin sideload route (ADR-035)

**What changed.** Product images reach WooCommerce through a mu-plugin REST route,
`POST /wp-json/urumi/v1/media`, that accepts `{filename, image_base64}` and calls
`media_handle_sideload`. It is installed by the wp-setup Job next to the existing
internal-REST mu-plugin. Authentication is the EXISTING WooCommerce consumer
key/secret pair (`woo-secrets`): WooCommerce's REST auth only processes its `wc/*`
namespaces (verified live — a request with valid Basic ck/cs to a custom namespace
arrives with no authenticated user), so the route validates the Basic pair itself
with the exact scheme WooCommerce stores keys under (`wc_api_hash(ck)` lookup,
`hash_equals` on the secret), rejects read-only keys for POST, binds the request to
the key's WP user with `wp_set_current_user()`, and then enforces an `upload_files`
capability check. No delete endpoint exists on the route (no delete tools, ever).

**Spike results (live, 2026-10-18).**
- (a) `POST /wp-json/wp/v2/media` with an Application Password: WORKS over plain
  HTTP on this cluster (201) — but only as a side effect of the internal-rest
  mu-plugin marking every `/wp-json/` request as HTTPS. Rejected: it introduces a
  SECOND store credential (creation, storage, rotation, and a different trust
  story than woo-secrets), while product attachment still needs the Woo key.
- (b) mu-plugin sideload route: verified live with the existing `woo-secrets`
  key — base64 PNG in, attachment id + URL out; SVG rejected 415 by magic-byte
  check; attach via `wc/v3 products/{id} images[{id}]`; URL serves 200
  `image/png`. Uses one existing credential, zero network changes.
- (c) `images[].src` with a short-lived gateway URL: rejected — WordPress would
  have to fetch the URL from the gateway and the deny-by-default NetworkPolicy
  gives WordPress egress only to MariaDB (helm networkpolicy.yaml), so it needs a
  NetworkPolicy opening (and a public-from-cluster path).

**Why.** One existing credential, one network path that already exists
(woo-mcp -> wordpress:80), and the smallest new attack surface: a single
capability-checked route that accepts bytes and stores a file. The server
generates the stored filename (the caller's is never used), accepts only
PNG/JPEG/WEBP by real magic bytes (`getimagesize` on the bytes), caps size at
5 MB, and delegates the rest to WordPress' own media handling (allowed-mime and
`wp_check_filetype_and_ext` re-checks; SVG cannot pass either layer). The heavy
validation (magic bytes, 5 MB cap, 4096 px cap, Pillow re-encode to strip
EXIF/GPS and polyglot payloads) happens in the callers (woo-mcp tool and gateway
upload endpoint) before any bytes are sent.

**Postscript (re-deploy finding, 2026-10-18).** The first live deploy of the
mu-plugin exposed a WordPress interaction the spike had not hit: because the
internal-rest mu-plugin marks `/wp-json/` as HTTPS, WordPress considers
application passwords AVAILABLE on REST requests, so its own
`determine_current_user` gate (priority 20) tries to authenticate a Basic
`ck_...` header as a WP username and rejects the whole request with 401
`invalid_username` BEFORE any permission callback runs — but only on the
non-`wc/*` namespaces WooCommerce's own REST auth ignores. The route now
authenticates the Basic pair itself on `determine_current_user` at priority 10,
ONLY for `/wp-json/urumi/*` paths (a valid ck/cs sets the current user, so
WordPress' application-password check is skipped; a read-only key never sets a
user). The permission callback then enforces the `upload_files` capability on
top. Same credential, same scheme, deterministic order — verified live
(HTTP 200, attachment created, audit row success with no bytes).

**Known trade-offs.** The mu-plugin accepts base64 JSON, which inflates payload
size ~4/3x versus multipart (acceptable at a 5 MB cap over a ClusterIP path). It
trusts WordPress' mime whitelist as the final gate, so a future WP change that
allows SVG by default would silently widen the route; the gateway/woo-mcp side
independently rejects SVG. The key lookup adds one indexed DB query per upload.

## 2026-10-18: I1 integration — parity light-mode deviations classified (B4)

Three light-mode parity differences found during the I1 integration pass, each
classified and handled:

1. **audit `.note-banner` background — REAL REGRESSION (fixed).** Mockup
   `rgb(231,234,240)` (#E7EAF0 = `--primary-tint`), live was `rgb(244,243,239)`
   (#F4F3EF = `--surface-2`). The note banner is an F1-2 side effect: `styles.css`
   aliases that shadow a real theme token clobbered it. Restored to the approved
   colour via the `--primary-tint` token (no literal added anywhere).
2. **servers `.btn.btn-secondary` padding — SAMPLING DIFFERENCE (fixed selector).**
   Mockup's first `.btn.btn-secondary` is a row action button (`btn-sm`,
   6px 12px); live's first is the header "Permissions" button (9px 16px). The
   parity selector now pins `.btn.btn-secondary.btn-sm` so both sides sample the
   same row action button; the header button is intentionally the larger base
   size and matches the mockup's base `.btn` (9px 16px).
3. **servers `.switch .track` colour — SAMPLING DIFFERENCE (fixed selector).**
   Mockup's first switch is an enabled server (checked track = ink
   `rgb(20,23,28)`); the live first switch belongs to a disabled server
   (unchecked track = `rgba(20,23,28,.1)`). The parity selector now pins
   `.switch input:checked + .track` so both sides deterministically sample the
   enabled state. The track token values themselves are unchanged and correct.

## 2026-10-19: Storefront redesign - standalone block theme urumi-store (ADR-037)

**Decision.** The storefront is a STANDALONE WordPress block theme, `wp-content/
themes/urumi-store/`, with no parent theme, shipped in the new store-assets image.

**Why standalone.** The stock image is WordPress 6.6, which does not ship Twenty
Twenty-Five (it ships Twenty Twenty-Two/Three/Four). A child theme of any of those
would inherit a different token system and a `theme.json` merge fight; the redesign
needs its own token family (the same one the dashboard uses: ink #14171C, greige
page, Dusk gradient, 12/24/40/999 radii, layered shadows). A standalone block theme
with `theme.json` (version 3) plus block templates/parts/patterns expresses ~90% of
the design with zero custom CSS for the layout; `assets/styles.css` carries only
what blocks cannot (nav, tile hover, cart/checkout restyle, motion, responsive).

**Why not a classic theme.** The store must keep the WooCommerce BLOCK cart and
checkout (restyled, not replaced: no field hidden, reordered or removed, COD stays
default), and block templates give per-template control (front page, shop, category
tint pages, product, cart, checkout, search, 404, order received, my account)
without PHP template sprawl.

**Fonts.** Instrument Serif (display) + Inter variable (UI), both OFL, self-hosted
woff2 latin subsets inside `theme/assets/fonts/`, taken from the official
fontsource release packages (fontsource is the same upstream glyph data with
stable file naming and ready-made latin subsets - one-line justification for the
choice of source). `font-display: swap` in theme.json, the display font is
preloaded in `wp_head`, and no font request leaves the origin.

## 2026-10-19: Storefront delivery - store-assets image + initContainer copy (ADR-038)

**Decision.** A new static image `store-assets` (built from `store/`: theme +
`products.json` + images; repo/tag values-driven, `ghcr.io/urumi/store-assets` in
prod, `urumi/store-assets` local via `make store-assets-image`) is copied into the
wp-content volume by an initContainer on EVERY WordPress pod start.

**Why the copy is mandatory.** The official WordPress image only populates
wp-content on the FIRST start of an empty volume; an existing PVC is never
refreshed from the image. Without an explicit copy step every redeploy would
silently run the previous theme. The copy is idempotent and copies directory
CONTENTS (`cp -rf src/. dst/`): a plain `cp -rf src dst` NESTS the tree when dst
already exists, which leaves a stale theme live beside the new one (observed and
fixed during this pass). Files are chowned 33:33 (www-data) to match the volume.

**Security posture.** The initContainer runs as root with CHOWN/DAC_OVERRIDE/FOWNER
only (the wp-content volume is www-data-owned; documented because the main
wordpress container also needs the same relaxation, so no NEW relaxation was
introduced). The image contains no secrets and no code that runs at runtime.

## 2026-10-19: Storefront seeding - idempotent by SKU, admin edits protected (ADR-039)

**Decision.** `store/products.json` is the single source of truth. The wp-setup
Job seeds through wp-cli/PHP BY SKU: create missing products, attach the catalog
image (temp-copy sideload into the media library), set the category, and mirror
the `new` flag to the WooCommerce featured flag (featured == new on this store).

**Re-run semantics.** On a re-run the seed never duplicates (SKU lookup via
`wc_get_product_id_by_sku`) and never overwrites admin edits (name, price, copy,
image, categories are left as the admin set them) - only missing bits are
backfilled (image when none, category when none, append-only so admin categories
are never disturbed). `STORE_SEED_FORCE=1` (values `wpSetup.seedForce`) is the
explicit operator path back to the catalog: it updates name/price/copy, re-attaches
the catalog image and REPLACES the category terms exactly. Orders and customers are
never touched by seeding. Proven live: second run reports
`created=0 kept=12 updated=0 images=0 (force=0)`.

**Seeded state.** The job also (idempotently) activates urumi-store, sets the front
page and posts page, creates the About and Shipping and returns pages (honest copy:
cash on delivery only, no carrier integration, demo notice in the footer), builds
the Primary menu, sets USD, keeps COD enabled and default, disables reviews and
enables guest checkout. Third-party calls (emoji script, gravatar, oEmbed, resource
hints, external fonts) are removed at the theme level.

## 2026-10-19: Orphan media reset runs in the wordpress pod, not via REST (ADR-040)

**Decision.** The demo reset purges orphan media with `scripts/demo-reset-media.php`
executed INSIDE the wordpress pod (`kubectl exec ... -- php`), driven by
`scripts/demo-reset.sh`. An attachment is kept iff it is the featured thumbnail of
one of the 12 seeded products (SKUs from store/products.json); everything else is
deleted with `wp_delete_attachment(id, true)`.

**Why not wp/v2/media.** The Woo consumer key cannot authenticate wp/v2 routes
(verified live: the internal-rest mu-plugin marks /wp-json/ as HTTPS, WordPress
then tries application-password auth, and `ck_...` is not a username -> 401
invalid_username), and the F3 upload route deliberately has no delete endpoint
(ADR-035: no delete tools, ever). Adding a second store credential (an application
password) just for cleanup was rejected. The wordpress pod already owns the DB and
the upload filesystem, so `wp_delete_attachment` there is the capability-scoped
path; the reset keeps its local-kind guard (ADR-032) for the new exec.

## 2026-10-19: Pod security hardening — one shared securityContext helper (ADR-041)

**Decision.** Every container and init container in the chart renders its
securityContext from ONE helper (`urumi.securityContext` in `_helpers.tpl`),
driven by a per-workload values block (`podSecurity.workloads`): runAsNonRoot
with an explicit uid/gid, `allowPrivilegeEscalation: false`, ALL capabilities
dropped, `seccompProfile: RuntimeDefault`, and a per-workload
`readOnlyRootFilesystem`. Pod-level fsGroup (same helper) makes PVC mounts
group-writable for the non-root uid, which is what let the root
`fix-permissions` chown initContainer be deleted entirely.

**Where the uid comes from.** gateway/woo-mcp/demo-* run as uid 1000 (their
images), dashboard as 101 (nginx), postgres as 70, mariadb as 999 (mysql),
wordpress as 33 (www-data), wp-setup as 33, the store-assets copier as 33 and
the busybox wait-probes as 1000. All of these live in
`values.podSecurity.workloads` — nothing is hardcoded in a template.

**readOnlyRootFilesystem = true** for gateway, dashboard, woo-mcp, demo-time,
demo-notes (their `/tmp` needs became emptyDirs) and postgres (emptyDirs for
`/tmp` and the socket dir `/var/run/postgresql`, plus fsGroup 70). FALSE for
wordpress, mariadb and the wp-setup job: the WordPress image's entrypoint writes
`wp-config.php` into the image layer each start and MariaDB needs its runtime
dirs on the image fs. Residual: those three containers can write their own
filesystem (they still run as non-root with no capabilities) — recorded in
THREAT_MODEL.md.

## 2026-10-19: Dedicated ServiceAccounts, no automounted tokens (ADR-042)

**Decision.** One ServiceAccount per workload (`urumi-<component>`), rendered by
`helm/templates/serviceaccounts.yaml`, every one with
`automountServiceAccountToken: false` on both the SA and the pod. The single
exception is the wp-setup hook SA (`automountServiceAccountToken: true`): that
job PROVES an API-server need — it writes the generated Woo CK/CS into the
`woo-secrets` Secret through the K8s API, under a Role scoped to exactly
`secrets get/create/patch/update` in the namespace. Every other workload was
verified by grep to contain no API client and runs green with no token
(scripts/verify-hardening.sh checks the mount is absent on all eight). The
chart has no ClusterRole and exactly one Role (wp-setup, secrets only).

## 2026-10-19: Custom hardened WordPress + wp-cli images; everything non-root (ADR-043)

**Decision.** `src/wordpress` builds the WordPress image FROM the pinned
`wordpress:6.6-php8.2-apache` with three deltas: Apache listens on the
unprivileged 8080 (`ports.conf` + vhost), `/var/www/html` and the apache
runtime dirs are owned by www-data (uid 33), and `USER 33`. The wp-setup hook
runs from `src/wp-cli` (the upstream `wordpress:cli-php8.2` with /var/www/html
chowned to www-data) so the whole job runs as uid 33. The store-assets
initContainer runs as uid 33 with pod fsGroup 33, so it needs no chown and no
capabilities; the root `fix-permissions` initContainer is deleted. MariaDB runs
as uid 999 (the official image's supported non-root mode; its entrypoint skips
chown when not root) with fsGroup 999 over the existing root-initialised PVC.
The pod port change is values-driven end to end: `wordpress.containerPort`
(8080) with `wordpress.service.port` keeping 80, so the Service, Ingress, the
woo-mcp `WOO_URL`, the wp-setup waits and the NetworkPolicy ports all follow
values.

**The one credential leak found and fixed on the way:** Apache's default
`combined` LogFormat logs `%u` (REMOTE_USER), which for `/wp-json/` Basic auth
is the Woo CONSUMER KEY — a credential half leaked into pod logs on every MCP
REST call (observed in real pod logs). The hardened image redefines the
`combined` format with `%u` replaced by a literal `-`; a fresh Basic-auth call
logs no key material (verified by re-scanning pod logs).

## 2026-10-19: Login lockout + Secure session cookie (ADR-044)

**Decision.** The dashboard login endpoint counts failures per username AND per
client IP (in-memory sliding window; `auth/login_throttle.py`). After
`login_lockout_attempts` (5) failures inside `login_lockout_window_seconds`
(300s) the next attempt gets `429` with the generic text "too many attempts,
retry later" — before any credential work and with no user-existence leak. The
lockout TRANSITION writes exactly one `login.lockout` admin event (reason +
client IP; the attempted password is never stored), on top of the existing
`login.failed` trail. A successful login clears the counter.

**Accepted residual:** the counter is in-memory, so it is PER REPLICA — with N
replicas an attacker gets `attempts x replicas` tries and a pod restart clears
the counters. Scaling out requires a shared store (Redis/PG); not
half-implemented. The session cookie gained `Secure` as a setting
(`gateway.sessionCookieSecure`, values-prod sets true; local kind stays plain
http so it stays false). SameSite stays `lax`; `strict` was not verified live so
it is not claimed.

## 2026-10-19: NetworkPolicy ports are values-driven (ADR-045)

**Decision.** The default-deny + explicit allows are unchanged in shape, but
every port now comes from values (container ports for pod-side rules: wordpress
8080, dashboard 8080, gateway 8000; the ingress-nginx namespace selector is the
`networkPolicy.ingressNamespace` value). This was load-bearing: NetworkPolicy
port matches are evaluated against the POD port (post-DNAT), so moving the
WordPress/dashboard containers to 8080 required the policy to allow 8080 — the
policy ports are `wordpress.containerPort` / `dashboard.port` / `gateway.port`,
never hardcoded. Enforcement is proven by scripts/verify-hardening.sh: a
throwaway pod is BLOCKED from woo-mcp/notes/time/postgres/mariadb, the gateway
reaches every upstream, and even the probe pod's own egress is default-denied
(it needs a scoped egress policy to reach the gateway at all).

## 2026-10-19: Security headers + CSP with no inline scripts (ADR-046)

**Decision.** The dashboard nginx and the gateway API both send:
Content-Security-Policy (`default-src 'self'; script-src 'self'; style-src
'self'; img-src 'self' data:; font-src 'self'; connect-src 'self';
frame-ancestors 'none'; base-uri 'self'; form-action 'self'`),
X-Content-Type-Options nosniff, Referrer-Policy no-referrer, X-Frame-Options
DENY and an empty Permissions-Policy. The dashboard's theme-flash inline script
moved to an external `/theme-init.js` so `script-src 'self'` holds with no
'unsafe-inline' and no hashes. nginx `add_header` inheritance is handled (the
`/assets/` location repeats the block). Verified in a real browser: zero CSP
console errors, app renders. One Playwright harness quirk was fixed, not
worked around: `waitForFunction` is eval-based (CSP correctly refuses it), so
scripts/verify-chat-upload.mjs polls with `page.evaluate(fn)` (CDP
callFunctionOn, CSP-respecting).

## 2026-10-19: One SSRF-safe client factory; connect-time revalidation proven (ADR-047)

**Decision.** The two upstream-call sites (gw_mcp/router.py and
gw_mcp/aggregator.py) built identical nested httpx factories; both now share
`registry.validator.ssrf_safe_client_factory(timeout)` — the ONLY client
factory the gateway uses upstream, with `follow_redirects=False` (a 30x must
never be chased toward a private IP after the original host was validated) and
the gateway's own timeout. Tests pin: save-time URL shape rejection
(127/localhost/metadata/10.x/172.16.x/192.168.x/IPv6 loopback/userinfo/scheme),
connect-time resolution rejecting literal private IPs, hostnames that RESOLVE
private (mocked resolver), and decimal/hex inet_aton forms ("2130706433",
"0x7f000001", "127.1" — glibc's resolver accepts them; the resolved-address
check is what blocks them), plus the factory's no-redirects contract.

**Found while scanning pod logs (ADR-043 note):** Apache's `combined` format
logs `%u` (REMOTE_USER) — for /wp-json/ Basic auth that IS the Woo consumer
key. Fixed in the hardened image by redefining the format with `%u` dropped;
pod-log scan now reports 0 key-shaped strings.

## 2026-10-20: GHCR images, baked WP core + WooCommerce, offline wp-setup (ADR-048)

**Decision.** All 8 custom images are built by `scripts/push-images.sh` with
docker buildx for `PLATFORMS` (default linux/amd64) and pushed to
`ghcr.io/<GHCR_OWNER>/<name>:<tag>`, where the tag is `<appVersion>-<short git
SHA>` pinned in values-prod.yaml (never `:latest`). The wp-cli image BAKES
WordPress core (sha1 pinned from the official release) and the WooCommerce
9.4.2 zip (sha256 recorded in src/wp-cli/woocommerce-9.4.2.zip.sha256) at build
time; the hardened wordpress image bakes the full core into /var/www/html. The
wp-setup hook copies the baked core and installs the plugin from the baked zip:
it issues NO network request, and the wp-setup NetworkPolicy now has NO public
internet rule (only wordpress/mariadb/K8s API). `make images-push` is the
one-liner (owner/token via env or hidden prompt, token only ever reaches docker
login via stdin); `make smoke-images` proves every build context builds, the
containers boot, and no secret-like files land in any image.

**Fresh-install crashloop found by the rehearsal:** the upstream wordpress image
ships a sparse docroot and the entrypoint tar-copies core into it on every boot;
as a NON-ROOT container on a FRESH wp-content volume that extract fails with
"tar: ./wp-content: Cannot change mode to rwxrwxrwx: Operation not permitted"
(the volume mount root is owned root:fsGroup) and the pod crashloops - a fresh
install on the hardened image was BROKEN (the old root-era chart never hit it
because root could chmod). Baking the core into the image docroot makes the
entrypoint's copy step never run, which fixes fresh installs AND removes the
per-boot copy cost. Measured fresh installs: BEFORE (download path) 2m42s,
AFTER (baked, zero-internet egress) 3m37s, both wall-clock of
`helm upgrade --install --timeout 15m`. The wp-setup NetworkPolicy now carries
NO 0.0.0.0/0 rule, so a fresh install succeeding under it is the offline proof;
NetworkPolicy ENFORCEMENT is real on kind too (kindnet): a control test in a
scratch namespace showed no-policy CONNECT_OK, default-deny CONNECT_FAIL, and the
allow rule CONNECT_OK again (documented in DEPLOY_VPS.md). The blocked-connection
probe is still repeated on the VPS as a live confirmation of the real k3s CNI.

## 2026-10-20: Real client IP behind the ingress (ADR-049)

**Decision.** The gateway starts uvicorn with
`--forwarded-allow-ips "$FORWARDED_ALLOW_IPS"` (image CMD), set from the new
`gateway.trustedProxies` value. Empty (default) trusts NOBODY: the login
throttle and audit log see the immediate peer. The kind local values trust ONLY
the ingress-nginx controller pod IP; the VPS trusts the k3s pod CIDR (the
controller sources from it). uvicorn then takes the first UNTRUSTED hop in
X-Forwarded-For from the right, so a client-supplied `X-Forwarded-For:
203.0.113.9` is ignored (ingress-nginx prepends the real client to the chain)
and the throttle keys on the true client.

**Proven live** (two throwaway pods with distinct pod IPs through the real
ingress-nginx on kind): client A (10.244.0.193) locked itself after 5 failures
(429 on the 6th); client B (.194) was NOT locked (401 on a fresh username);
client B's spoofed X-Forwarded-For did not bypass - it was locked by its REAL
address which had one prior failure (429 on the 5th attempt of the second
batch); the audit row records the true client:
`login.lockout ... {"reason": "lockout", "client_ip": "10.244.0.194"}` - never
the spoofed 203.0.113.9, and never the ingress pod IP.

**Residual (documented, accepted):** trusting a pod CIDR means an IN-CLUSTER
pod could also spoof X-Forwarded-For (external clients' IPs are outside the
pod CIDR and cannot). Narrow the value to the ingress controller pod IP(s)
when possible; the local kind values trust exactly the controller IP
(10.244.0.2) for this reason.

## 2026-10-20: Explicit helm timeout + atomic; LLM key via hidden prompt (ADR-050)

**Decision.** Every install/upgrade path in the Makefile uses
`--timeout 15m --atomic --wait` (helm-local, helm-prod, make upgrade); the
wp-setup hook provisions WordPress on a cold cluster, so the timeout must cover
a cold install (observed 2m42s-3m37s on the 2-CPU node), and --atomic makes a
failed upgrade roll itself back (rehearsed twice in docs/UPGRADE_ROLLBACK.md).
The LLM key is created by `scripts/create-llm-secret.sh`: read -rs hidden
prompt, piped via stdin to `kubectl create secret ... --from-file=/dev/stdin` -
the key never appears in argv, shell history, a repo file, or a log. No secret
is ever regenerated by an upgrade (ADR-016 lookup-guard stands; verified by
resourceVersion comparison in the prod-readiness session).

## 2026-10-20: ACME HTTP-01 solver NetworkPolicy ships in the chart (ADR-051)

**Decision.** The chart renders `urumi-allow-acme-solver` (template name =
`<fullname>-allow-acme-solver`, which renders as `urumi-allow-acme-solver` at
release name urumi) whenever `global.tlsEnabled` is true: podSelector
`acme.cert-manager.io/http01-solver: "true"`, ingress ONLY from the ingress
controller namespace (the same `networkPolicy.ingressNamespace` selector the
public-tier policy uses) on port `networkPolicy.acmeSolver.port` (default 8089).
No egress rule: the solver only serves the challenge.

**Why.** On the first real VPS deploy (2026-10-20), cert-manager's HTTP-01
solver pods were blocked by the chart's default-deny: the challenge request from
Let's Encrypt reached ingress-nginx, nginx got 502 reaching the solver pod, and
the CertificateRequest hung. A manually applied policy of this exact shape fixed
issuance immediately. That policy must not stay a kubectl artefact: it is now
values-driven in the chart (port from values, namespace selector shared with the
public-tier policy). Because cert-manager creates solver pods in the SAME
namespace as the Ingress (urumi), a namespace-local policy with the solver label
is sufficient, and the solver still has no egress.

**Adoption note.** The live cluster already carries a manually created
`urumi-allow-acme-solver`. Helm refuses to adopt a resource it does not own
("ownership metadata" / already-exists error), so delete the manual one RIGHT
BEFORE the first upgrade that ships this chart:
`kubectl delete networkpolicy urumi-allow-acme-solver -n urumi`.
The solver only exists while a challenge is in flight, so deleting it between
renewals has no effect on the issued certificate.

**Scope.** Rendered only when TLS is enabled: with `global.tlsEnabled=false`
(kind local default) there are no ACME solver pods, and rendering the policy
anyway would be dead manifest. Verified: helm template with values-prod.yaml
renders exactly one such policy; with values-local.yaml it renders none.

## 2026-10-21: tools/list serves a per-upstream stale cache instead of dropping tools (ADR-052)

**Decision.** When one upstream's live tools/list fails inside
`fanout_list_tools` (timeout, connection error) or its circuit breaker is open,
the gateway now serves that server's LAST-KNOWN cached tools (the `tools` table,
kept warm by the health loop) instead of silently omitting the server from the
merged list. The response's `_meta.warnings` carries
`{"server": <slug>, "error": <safe label>, "stale_cache": true}` so callers can
see the degradation. A server with no cached rows keeps the old behaviour (plain
error warning, no invented tools). RBAC deny filtering still applies to stale
tools (the filter runs on the merged list, after the fallback), and
`tools/call` enforcement is untouched (live rule read, ADR-033).

**Why.** Reproduced live: with an empty deny table, a member API key listed 10
tools and an admin 13, and repeated calls flipped between 10/11/13 - the
differences were per-request upstream timeouts (gateway log: `health fail notes
category=timeout`), NOT per-role filtering. One slow upstream made every MCP
client (e.g. Cursor) see fewer tools than are allowed. The cache fallback keeps
`tools/list` stable: 20/20 live calls returned all 13 tools after the fix, with
the stale marker present on the requests where the old code would have dropped
tools.

**Consequence.** During an upstream outage clients keep seeing the server's
tools (stale schemas) and calls to them fail with the normal upstream/circuit
errors; a brand-new server that never answered has no cache and stays hidden, as
before. `stale_cache: true` in `_meta.warnings` is the clients' signal.

## 2026-10-21: Permissions dialog scrolls its body; header and footer fixed (ADR-053)

**Decision.** The dashboard's Permissions dialog (`Servers.tsx`) uses a
`modal-tall` layout: the dialog is capped at `100dvh - 2*padding` (100vh
fallback), the header (title, restricted-count chip, Close) and the footer
(Save) are fixed, and only the `.modal-body` (tool list) scrolls. The generic
`.modal` also gains a `max-height` + `overflow-y: auto` so no dialog can ever
overflow the viewport again.

**Why.** Reproduced in a real browser (Playwright, 1440x960): the dialog was
1289px tall in a 960px viewport inside a fixed, non-scrollable backdrop; the
Save button sat at y=1242, outside the viewport, and playwright could not scroll
to it. The network log showed the dashboard NEVER sent `PUT /api/permissions`
while the backend persisted a replayed PUT fine (200, row in
`tool_permissions`, GET reflects it). So the reported "toggle does not stay
off / 0 restricted" had one root cause with the unscrollable dialog: the Save
button was unreachable, so no save ever happened. After the fix the same
browser flow toggles a tool off, scrolls to Save, gets PUT 200, and after
closing/reopening shows "1 restricted for members" with the switch still off -
at 1440x960 and 390x844.

## 2026-10-22: Landing page is a static no-build site served by the dashboard nginx pattern (ADR-080)

**What changed.** `src/landing/` is a one-page site: plain HTML, CSS and a little vanilla JS, no
framework and no build step. It is served by a tiny nginx image (`FROM nginx:1.27-alpine`) copied
from the dashboard image pattern: unprivileged 8080, run as uid 101 via the chart, read-only root,
and the same three emptyDirs (/tmp, /var/cache/nginx, /var/run) that let non-root nginx boot. The
security headers are byte-identical to the dashboard's (CSP self-only with no inline scripts, the
theme bootstrap lives in the external theme-init.js, nosniff, no-referrer, DENY framing, empty
Permissions-Policy) and the add_header inheritance gotcha is handled the same way. The page makes
ZERO external requests: system fonts only, inline SVG only, no CDN, no analytics, no trackers, and
the optional demo video renders as a link out, never an embed.

**Why.** The brief asked for a fast, honest one-page site at the apex domain, and the repo already
has a proven hardened static-serving shape (the dashboard). Reusing it keeps the security story in
one family instead of inventing a second nginx config.

**Alternatives considered.**
- A React/Vite app for the landing: rejected, a build step and 100x the JS for zero benefit on a
  static page (the brief forbade frameworks anyway).
- An embed for the demo video (YouTube/iframe): rejected, it breaks the zero-external-request
  guarantee and the CSP; a link out keeps both and the block stays hidden until videoUrl is set.

**Known trade-offs.** The empty-value Permissions-Policy header is silently dropped by nginx
(verified by curl: five of the six headers arrive; the sixth is the empty one). This matches the
dashboard/gateway behaviour exactly, so the family stays consistent. Editing features.js requires
an image rebuild by design (the config ships inside the image; there is no Secret wiring for a
static page).

**Verification.** `scripts/landing-verify.mjs` (playwright-core): 1440 and 390, light AND dark,
into gitignored artifacts/landing/. Gates: zero external requests, zero console errors, no
horizontal scroll and no element past the viewport at either width, 32-pair AA contrast gate per
theme (one real failure found and fixed: the sample-data chip used light text on a mid-tone tint;
it now uses the dashboard's on-tint rule, dark ink on tints in both themes), pre-paint theme
applied in both modes, reduced-motion collapses the flow animation (computed 1e-05s), and with the
default config the Beyond-the-brief and video sections stay hidden. Page weight 52KB raw, 15.5KB
gzip. docker build + docker run as uid 101 with tmpfs emptyDir mimics, curl headers checked.

## 2026-10-22: Landing theme is dark-first with dashboard-family tokens (ADR-081)

**What changed.** The landing ships dark by default with a light mode. Tokens mirror
src/dashboard/src/styles/tokens.css: same neutral scale (dark surfaces #14161B/#1C1F26/#22262F,
light greige #ECEBE7/white), same ink pill primary (light-on-dark in dark mode), same accent tints
(periwinkle, sky, blush) and the Dusk gradient restricted to one 3px strip on the hero code card.
No green accent anywhere. Theme resolution: stored choice in localStorage (try/catch), else
prefers-color-scheme, else dark. The pre-paint bootstrap is an external file (theme-init.js)
because the CSP forbids inline scripts; the nav toggle stores the choice. Radii (24/14/10/999),
shadow family and the 20px spacing grid are the dashboard's; the type scale extends it with display
sizes (h1 up to 54px) for a marketing page. Final values documented in docs/LANDING_DESIGN.md.

**Why.** The brief said dark-first with a light mode and one family with the product. The
dashboard's dark set already passed contrast review, so reusing it avoids inventing (and
re-measuring) a second palette.

**Alternatives considered.**
- Light-first like the dashboard app: rejected, the brief explicitly said dark-first for the site.
- A separate landing palette: rejected, two colour systems would read as two products.

**Known trade-offs.** The dashboard defaults to Light and remembers System-less choices; the
landing defaults to Dark. They share the token VALUES, not the default. A visitor moving from site
to app sees the app start light unless they pick dark there; acceptable, the site is the storefront
and the app is the tool.

## 2026-10-22: Beyond-the-brief and the video block are config-driven from features.js (ADR-082)

**What changed.** `src/landing/features.js` is the single config file: `repoUrl` (announcement bar
+ nav + footer, defaulting to the Chart.yaml home), `videoUrl` (empty = the video section stays
hidden), and `features`: multi-store provisioning, hosted MCP servers, OAuth, compact tool mode,
rate limits, metrics. Every item ships `enabled: false`; main.js renders ONLY enabled items, and
when none are enabled the whole section stays hidden. main.js also derives the dashboard/store
links from the apex host the page is served on (dashboard.<apex>, store.<apex>, the same
convention the Helm values use), with optional explicit overrides in the same file, so the static
page carries no hardcoded hostname and the hero code card shows the real /mcp URL of the
deployment.

**Why.** The page must only claim what exists on the branch at build time. A flipped boolean that
ships before its branch merges would be a false claim on a public page; the flip therefore lives in
the image build, not in cluster state.

**Alternatives considered.**
- Helm values -> rendered config: rejected, the page is static and the flag belongs to the site's
  content build, not the release; also avoids wiring a ConfigMap for one boolean.
- Rendering disabled items greyed out: rejected, showing "OAuth" as a grey card still advertises a
  thing that does not exist; hidden means honest.

**Known trade-offs.** Flipping a flag requires `make landing-image` plus a landing rollout. The
section disappears entirely while all items are off, so the code that renders it is untestable in
the default build; scripts/landing-verify.mjs asserts the default-hidden state, and the render path
is six lines of DOM building in main.js.

## 2026-10-22: Helm landing component, separate files, apex Ingress with a dedicated cert (ADR-083)

**What changed.** The landing deploys from five NEW templates (nothing existing was edited except
values files and the schema): landing-deployment.yaml (dashboard-shaped: uid 101 via the shared
securityContext helper, readOnlyRootFilesystem, probes on /, small resources 10m/32Mi requests),
landing-service.yaml (ClusterIP), landing-serviceaccount.yaml (automountServiceAccountToken false;
kept in its own file instead of serviceaccounts.yaml to stay conflict-free),
landing-networkpolicy.yaml (the ONLY opening for the landing pod: ingress from the
ingress-controller namespace on the values port; no egress rule at all, a static server needs not
even DNS), and landing-ingress.yaml. The Ingress serves the APEX host from the `landing.host`
value; TLS follows the existing cert-manager pattern (same annotations object, same tlsEnabled
gate) but with a DEDICATED secretName (`landing.tlsSecret`, default urumi-landing-tls) because
cert-manager issues one Certificate per Ingress and two Certificates cannot share a Secret. The
Ingress renders only when `landing.host` is set: an empty host would render a catch-all rule that
steals traffic from the store/dashboard Ingress. `landing.enabled` defaults FALSE in values.yaml
and true in values-local.yaml (kind apex 127.0.0.1.nip.io). No hostname is hardcoded in any
template. Makefile gained `landing-image` (same build+import style); push-images.sh and
smoke-images.sh list the ninth image.

**Why.** Merge safety first: every new manifest is a new file, so other branches cannot conflict
with it; the only shared-file touches are the values appends and one schema property.

**Alternatives considered.**
- One combined Ingress object edited inside ingress.yaml: rejected, it would put the landing in the
  highest-conflict file in the chart and entangle its rollout with the store/dashboard host list.
- Sharing the existing urumi-tls Secret: rejected (cert-manager shim creates a Certificate per
  Ingress; two Certificates claiming one Secret fight). The apex gets its own cert, renewed
  independently.
- Adding the landing port to the shared public-tier NetworkPolicy: rejected in favour of a
  dedicated policy that allows ONLY the ingress controller (the brief's wording); the landing needs
  no same-namespace callers and no egress.

**Known trade-offs.** Two certificates to renew instead of one, and the apex A record must point
at the server BEFORE enabling (documented in README). The local kind values turn the flag on with
the nip.io apex, which is plain HTTP locally (global.tlsEnabled false), same as the dashboard.

## 2026-10-22: Landing verification posture: docker + playwright + helm only, no cluster (ADR-084)

**What changed.** The landing branch was verified WITHOUT touching the kind cluster, kubectl or any
helm release (another session owns them): docker build + docker run as uid 101 with tmpfs mounts
mimicking the pod's emptyDirs, curl header assertions, scripts/landing-verify.mjs (Playwright:
screenshots 1440/390 in both themes into gitignored artifacts/landing/, zero-external-request,
overflow, contrast and console gates), helm lint with values-local and values-prod.example, and
helm template proving the flag renders four resources + the NetworkPolicy when on and ZERO landing
lines when off. npm ci in src/dashboard installed the existing playwright-core devDep for the
script; node_modules stay gitignored.

**Why.** The brief for this session forbade cluster access; every gate had to be runnable against
the image and the chart alone, and each must stay runnable later as a regression check.

**Known trade-offs.** The screenshots cannot be visually reviewed by this session (no image input
available), so the visual review is scripted proxies (geometry, overflow, contrast, computed
animation state) plus the saved PNGs for a human pass. The docker run needs explicit
--tmpfs ...:mode=1777 because plain docker tmpfs defaults are not uid-101-writable; the smoke test
encodes the same invocation.

## 2026-10-22: Landing polish pass, config-driven claims and copy button (ADR-085)

**What changed.** One timeboxed polish pass on the landing page, no Helm changes. (1) The nav's
sticky behaviour is now proven in-browser: the verify script scrolls to 1600px and asserts the
header's rect sits at the viewport top in all four cases, saving a mid-scroll screenshot per case.
(2) The hero config's gateway URL is config-driven: `landing.gatewayUrl` in features.js, empty by
default, falling back to `dashboard.<apex>/mcp` derived from the page host (same convention as the
Helm values, still no hardcoded hostname). The Authorization placeholder is now real visible text
(`Bearer <your-api-key>` with escaped angle brackets; the first version had raw `<your-api-key>`
in the HTML, which the parser swallowed as an unknown element, so the page silently showed only
"Bearer"). A Copy button puts the plain-text config on the clipboard (async Clipboard API with a
textarea fallback for plain-http, "Copied" feedback), proven by reading the clipboard back in
Playwright. (3) Hero strengthened with dashboard-accent tokens: a soft radial glow behind the
config block (`--hero-glow`), a subtle border, a one-time rise-in, a blinking caret, an accent
outline plus hover glow on primary buttons (`--accent-ring`) and stronger focus rings; more space
above the fold. All motion collapses under prefers-reduced-motion (re-verified 1e-05s). (4) Section
rhythm: a mono uppercase eyebrow above every section title and a hairline divider between
consecutive sections. (5) The features intro now reads "The gateway, the store and the team
controls below are all live in the demo", the queue intro lost its "branch" wording, and the page
contains zero "this branch" mentions. (6) The store claim is data-driven: `storeProductCount` in
features.js fills the "12-product catalog" phrase; null reads "a product catalog".

**Why.** The pass brief asked for exactly these seven items; the copy button and the two new config
keys keep the page's honesty invariant (claims come from one config file, not prose) while making
the hero actually usable.

**Known trade-offs.** The glow's horizontal inset initially pushed the 390px scrollWidth to 410px
(body's overflow-x clip hid the scrollbar, but the strict gate caught it); the glow now spills
vertically only. execCommand copy is deprecated but is only the plain-http fallback. The clipboard
round-trip test grants permissions explicitly; real browsers prompt or allow per-site.

**Verification.** scripts/landing-verify.mjs: all 4 cases OK with the new gates (sticky nav at
top, visible Bearer placeholder, derived URL without example.com, copy button present, store claim
"12-product"), zero external requests, 32/32 contrast pairs per theme, zero console errors.
Page weight 57.8KB raw, 17.0KB gzip.
