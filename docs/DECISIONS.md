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

## 2026-10-21: timezone fallback + time server default zone (ADR-054)

**What changed.** The chat system prompt now ALWAYS carries a concrete local
date/time: a missing or invalid client timezone falls back to the configured
`gateway.defaultTimezone` (env GATEWAY_DEFAULT_TIMEZONE, Helm value; base default
UTC, values-local sets Asia/Kolkata). Previously a missing/invalid tz produced a
prompt with NO local-time stamp, so "today" was ambiguous. The demo Time MCP
server gained the same idea: `demoTime.defaultTimezone` (env DEFAULT_TIMEZONE)
replaces the hardcoded UTC default in get_current_time when the caller omits a
zone; an explicit caller timezone still wins; an invalid configured zone surfaces
the tool's normal "Unknown timezone" error. The dashboard already sends
`Intl.DateTimeFormat().resolvedOptions().timeZone` with every chat request
(F1-8); validation against zoneinfo is unchanged (routes/chat._valid_tz), so an
attacker-supplied zone can only ever be a valid IANA name.

**Why.** The brief requires "today" in order questions to resolve in the user's
timezone with a configured fallback, and the Time server to take an optional
default zone. Frozen-clock tests pin the midnight boundary: 2026-10-21 18:30 UTC
is 2026-10-22 00:00 IST, and the IST prompt must say the 22nd while the UTC one
says the 21st.

**Known trade-off.** The configured default (Asia/Kolkata in values-local) stamps
a zone that may differ from the actual browser zone when the browser refuses to
send one; that is strictly better than no stamp, and the client tz always wins
when present.

## 2026-10-21: upstream credential encryption verified in place, not redone (ADR-055)

**Decision.** Upstream credentials were ALREADY encrypted at rest (Fernet,
key from the gateway-secrets Secret, stored as LargeBinary since migration
001; re-encrypted on key rotation by resync_internal_credentials, ADR-026).
Phase 0b therefore VERIFIES instead of re-implements: new
tests/test_credential_at_rest.py (ciphertext in the DB row, decrypt round-trip,
secret absent from every API response and from logs) plus a live DB inspection
in the gateway pod (`plaintext_in_db=False decrypts=True
value_matches_secret=True` for the notes credential). No migration is needed:
there are no plaintext rows to migrate - encryption shipped with the initial
schema, and every seeded credential is re-applied encrypted at startup.

**Rotation note.** Rotating FERNET_KEY (delete gateway-secrets, helm upgrade)
makes stored credentials undecryptable for seeded servers ONLY until the next
gateway start: resync_internal_credentials re-encrypts them from the Secrets.
Admin-added servers must have their credential re-entered after a key rotation.

## 2026-10-21: Prometheus /metrics + audit failure classification + Metrics page (ADR-056)

**What changed.**
1. Failure reasons are now CLASSIFIED and stored in the audit `error_code` field:
   the router raises `UpstreamCallError(category=...)` carrying the stable
   gw_mcp.categorize token (connection_refused, timeout, dns_failure, tls_error,
   http_error:<code>, protocol_error, invalid_response, auth_rejected, other),
   and both /mcp and the chat agent write that token into the audit row (the raw
   exception text is never stored or logged). `protocol_error` is NEW: an
   unparseable upstream JSON-RPC response used to be invalid_response. Chat tool
   calls that FAIL are now audited too (previously only successes/isError rows
   were; timeouts and upstream errors vanished from the trail) — same semantics
   as /mcp.
2. Prometheus /metrics on the gateway (prometheus_client — the one new runtime
   dependency, added to requirements.txt): tool_calls_total{server,tool,outcome},
   tool_call_duration_seconds{server} histogram, upstream_up{server} gauge
   (health loop + disable route), rate_limited_total{scope}. NOT exposed through
   the Ingress (verified: external /metrics on the dashboard host returns the SPA
   HTML; the Ingress has no /metrics path to the gateway) and in-cluster-only
   behind the default-deny NetworkPolicy. Optional METRICS_BEARER guard
   (gateway-secrets key METRICS_BEARER, empty by default; constant-time compare).
   Every metrics write fails safe — a metrics problem can never break a tool call.
3. GET /api/metrics (admin-only; members 403): the dashboard Metrics page
   aggregates computed from the AUDIT table over the last 24h — per server calls,
   errors, error rate, p50/p95 latency and top classified failure reasons.
   Parameterized SQLAlchemy; percentiles from a bounded newest-first sample (same
   pattern as /api/stats). New Metrics.tsx page + nav item (admin-only path), fleet
   table language, reason chips.

**Why.** Stand-out item 8: classified failure reasons on the server cards (already
shipped in the health columns) + in the audit trail, Prometheus metrics on the
gateway, and a Metrics page that needs NO Prometheus server (computed from audit
rows) so the demo shows the same numbers the audit table holds.

**Known trade-offs.** tool_calls_total has a `tool` label (bounded by registered
upstream tools, per the brief). Percentiles use the bounded-sample pattern rather
than SQL percentile_cont (portable across the sqlite test harness). /metrics is
unauthenticated by default in-cluster (token optional) — an in-cluster scraper is
added later by opening a NetworkPolicy exception for it; documented in
REVIEW_NEEDED.md.

## 2026-10-21: per-key and per-user rate limits in Postgres (ADR-057)

**What changed.** The /mcp in-memory per-key limiter is REPLACED by a Postgres-backed
limiter that holds across replicas:
- New `rate_limit_counters` table (migration 007): one row per (scope, minute),
  scope = `key:<api_key_id>` | `user:<user_id>`. Consumption is ONE atomic
  `INSERT ... ON CONFLICT DO UPDATE count = count + 1 RETURNING count`
  (sqlite dialect variant keeps the unit-test harness working). The limiter opens
  its OWN short session so it never interleaves with a request transaction; expired
  windows are swept by the background purge loop (5-minute keep).
- Limits: per key `gateway.rateLimit.perKeyPerMinute` (default 60) with an optional
  per-key ADMIN override (`api_keys.rate_limit_per_minute`, NULL = default;
  `PATCH /api/keys/{id}`, admin + CSRF, 1..10000, null clears; member 403; recorded
  in the admin trail as key.update), and per user
  `gateway.rateLimit.perUserPerMinute` (default 240) spanning EVERY key of the user
  AND the chat agent's tool calls (the chat loop consumes the same user counter on
  every routed tool call and streams a rate_limited tool event instead of routing).
- Rejection: HTTP 429 + `Retry-After: <seconds to minute end>` + JSON-RPC -32000
  naming the scope ("rate limit exceeded (key|user limit), retry after N seconds");
  audit row outcome `rate_limited` (CHECK constraint extended, migration 007) with
  error_code `rate_limited_key|rate_limited_user`; metric rate_limited_total{scope}.
- Fail-open: a broken counter (DB down) logs a warning and ALLOWS the call — a
  false 429 against an honest caller is worse than an availability bug.

**Why.** Stand-out 7b: rate limits must survive multiple replicas (Phase 4 needs
them shared), be per key AND per user, overridable per key by an admin, and the
chat agent must count against the user. Postgres is already the shared store —
no Redis, no new dependency.

**Known trade-offs.** The window is the wall-clock minute (fixed windows, not
sliding): a burst can straddle a boundary and get 2x the limit for a moment —
acceptable for a gateway demo and it makes Retry-After exact. Every /mcp call and
every chat tool call now costs one extra DB round-trip (the atomic upsert);
measured at ~1-2 ms locally. The limiter fails open (documented residual in
THREAT_MODEL terms: a DB outage disables rate limiting rather than the gateway).

## 2026-10-21: compact mode for many tools (ADR-058)

**What changed.** A client opts into compact mode per request with the
`X-Gateway-Mode: compact` header or `?mode=compact` on /mcp (no flag; opt-in per
client as the brief requires):
- tools/list returns ONLY two meta tools: `gateway__search_tools(query, limit?)`
  (keyword ranking over name+description across the RBAC-filtered catalogue:
  10 exact name / 8 name-prefix / 5 word-in-name / 3 word-in-description /
  1 substring; blank query = catalogue listing; limit default 20 max 50) and
  `gateway__call_tool(name, arguments)`.
- `gateway__call_tool` unwraps to the real tool and then flows through the SAME
  permission check, routing, timeout and audit code - the audit row and metrics
  carry the REAL tool name; the meta shell is invisible in the trail.
- The chat agent auto-switches above `gateway.compactThreshold` (env
  COMPACT_THRESHOLD, default 40; 0 = never): it sends only the meta tools and
  routes gateway__call_tool through the same path (permission, per-user rate
  limit consumed on the INNER call, audit with the real name; the search op is
  audited as server_slug=gateway).
- Default mode is unchanged: meta names are NOT special there (they fall through
  to the unknown-slug validation error, verified by test).

**Why.** Stand-out 4: with hundreds of tools the full tools/list drowns the
model's context (300 synthetic tools = 168,950 bytes; the two meta tools =
1,087 bytes, 0.6%). Two boring meta tools beat prompt engineering: no schema
bloat, any MCP client works without protocol changes, and permission/audit
semantics stay identical.

**Known trade-offs.** The model pays an extra round-trip per tool call (search,
then call). Meta tools cannot call meta tools (one level only). Rate limiting is
per HTTP request for /mcp (the meta call is one request - one consumption);
the chat loop consumes the per-user counter on the inner call as before. The
ranking is deliberately simple: name hits dominate description hits; no
embeddings, no new dependency.

## 2026-10-21: two gateway replicas, shared lockout, safe migrations (ADR-059)

**What changed.** The gateway now runs safely with more than one replica
(`gateway.replicas`; 1 in values.yaml/values-prod, 2 in values-local; PDB
minAvailable 1 renders only when replicas > 1; soft podAntiAffinity preferred):
- Statelessness is the design: dashboard sessions are signed cookies (no server
  session store), /mcp is stateless JSON-RPC-over-POST (no server-side MCP
  session), the tool catalogue is the DB-backed tools table, rate limits and the
  login lockout live in Postgres. No sticky sessions needed - documented rather
  than engineered around.
- Login lockout moved from process memory to the `login_failures` table
  (migration 008): one row per failed login per (kind='user'|'ip', key); the
  lockout counts rows in the window; every helper opens its OWN short session so
  a failure row survives the 401 that rolls the request session back. The old
  attempts x replicas residual is gone (proven by a two-app-instance test over
  one DB). Expired rows are swept by the background loop.
- Alembic migrations now take a Postgres ADVISORY XACT LOCK inside env.py
  (pg_advisory_xact_lock(715273)) so two replicas starting together serialize
  the upgrade: the second waits, then no-ops at head. Both pods started cleanly
  in the live run.
- Phase 2's Postgres rate limits were already replica-safe by construction.

**Why.** Stand-out 7a: the gateway must run with 2 replicas - stateless HTTP (no
sticky sessions; the Streamable HTTP transport holds no gateway-side session
state, so any replica can serve any request), migrations run once, and the
login lockout + rate limits shared through Postgres.

**Evidence (kind).** 2 replicas: one MCP session (same key, 25 sequential calls
through the ingress) survived the deletion of one replica - 25/25 OK, zero
failed calls; audit for the window: 25 rows, 0 duplicate request_ids, 25
successes (no gaps); make verify-llm ALL PASS against 2 replicas; regress-core
ALL CHECKS PASSED. NOTE: the replica probe runs from the HOST via the ingress
because the gateway's own default-deny EGRESS policy (correctly) forbids
in-pod calls to its own Service VIP - a policy quirk worth knowing, not a bug.

**Known trade-offs.** The audit writer is per-replica (each pod flushes its own
queue) - correctness unchanged, at-least-once per call. The chat MODEL_COOLDOWNS
fallback state stays per-replica (a cooldown taken on one replica does not
apply to the other; bounded by each replica's own fallback). Recreate rollout
strategy is kept (mutable image tags), so upgrades briefly take the gateway
down - unchanged single-replica behaviour for prod (1 replica unless Manav
raises it).

## 2026-10-22: startup schema gate + login-lockout fail-closed (RC, companions to ADR-061)

**What changed.** (1) After `alembic upgrade head`, the gateway reads
`alembic_version` through a SEPARATE connection and compares it with the head
the code ships with (`db/schema_check.py`). Mismatch -> clear ERROR log,
`/readyz` unready, exit code 3 - a rolled-back or silently-uncommitted migration
can never look healthy again. Proven live: pointing the check at a 006 database
while the code is at 011 raises `SchemaVersionMismatch` and exits 3; the
healthy path logs `schema version verified: db=011_oauth code=011_oauth`.
(2) Login lockout when `login_failures` is MISSING now fails CLOSED
(`ThrottleUnavailable` -> 503 on the login route) instead of silently failing
open; transient DB errors keep the ADR-057 fail-open policy; cleanup helpers
(record_success/purge) stay fail-open. (3) Chart fix: the OAuth env block was
nested under `provisioner.enabled`, so `oauth.enabled=true` was inert without
the provisioner - moved to top level (ADR-063 independence restored).
(4) The consent page's inline style violated the gateway CSP (style-src 'self')
and rendered unstyled; the consent response now overrides its own CSP with the
style's sha256 hash. (5) `configure_logging()` re-enables ALL `gateway.*`
loggers after alembic's fileConfig (the schema-check log line was being
silently dropped). Tests: test_schema_check.py, test_login_lockout_missing_table.py,
test_alembic_commit.py (real-Postgres commit proof, skips without
RC_TEST_DATABASE_URL; negative control = pre-ADR-061 env.py from 1bc1e7c logs
success but commits nothing).

## 2026-10-21: alembic advisory-lock commit bug fixed (ADR-061)

**What changed.** `alembic/env.py` took the ADR-059 advisory lock
(`pg_advisory_xact_lock`) BEFORE `context.begin_transaction()`. In SQLAlchemy
2.0 the SELECT autobegins a transaction; `MigrationContext` then sees the
connection already in a transaction, records it as an EXTERNAL transaction and
`begin_transaction()` returns a no-op - nothing ever commits the DDL. The
open autobegin transaction is rolled back when the connection closes: alembic
logged "Running upgrade ... 009_stores" and "alembic upgrade head done" while
the database stayed at 007. Every migration since ADR-059 (008 login_failures,
009 stores) was silently lost in the live cluster; nothing live caught it
because login lockout fails open and nothing else read the missing tables.
The fix takes the advisory lock INSIDE the migration transaction (semantics
unchanged: still serializes replicas, released at commit) and adds an explicit
`await connection.commit()` after `run_sync` as belt and braces. Verified live
on kind: version 007 -> 009 with `login_failures` and `stores` tables present.

**Why.** Phase 5's stores table exposed the bug (`column servers.internal does
not exist` on first store create). The phase-4 evidence over-claimed: "both
pods logged alembic upgrade head done" was true and meaningless - the proof
needed a post-upgrade DB read, which is now part of the live verification.

**Lesson recorded.** Migration verification must read the DATABASE after the
run (version + a new schema object), not trust the migration runner's own
success log.

## 2026-10-21: provisioner + multi-store (ADR-060)

**What changed.** A separate provisioner Deployment (own image, own SA,
least-privilege ClusterRole, NetworkPolicy-restricted to gateway pods plus a
shared X-Provisioner-Token) owns per-store namespaces + helm releases. The
gateway enforces roles/quotas (stores table, Stores dashboard page, per-user +
global maxima, slug rules, internal-upstream lifecycle) and calls the
provisioner; the provisioner drives `helm upgrade --install <slug> /charts/store`
into namespace store-<slug> with a bounded-concurrency semaphore, derives
readiness FROM THE CLUSTER (WordPress AND woo-mcp Deployments Available +
release deployed), labels namespaces urumi.io/managed-by=provisioner (code-level
adoption resistance; RBAC cannot filter namespaces by label), and reconciles
in-flight stores after restarts (deleting label FIRST, then uninstall, so a
crash mid-teardown resumes DELETING instead of resurrecting the store). Store
tool names are <slug>__* (internal Server rows, slug == store slug). WooCommerce
keys live ONLY in the store namespace (the wp-setup hook writes them there; the
gateway never sees them). Flag provisioner.enabled defaults FALSE (base+prod),
true only in values-local; stores.maxConcurrent=1 locally (2-core kind node
cannot fit two simultaneous wp-setup hooks; documented, brief-sanctioned).

**Live proof on kind (all commands + output in BUILD_LOG):** two stores
provisioned end-to-end (create -> Provisioning -> Ready, woo-mcp Connected,
<slug>__ tools via MCP tools/list and tools/call), NetworkPolicy isolation
proven 5/5 (own services reachable, cross-store mariadb+wordpress blocked from
woo-mcp AND wordpress pods), recovery proven (provisioner force-killed
mid-provision; reconcile resumed; store reached Ready), chat agent compared
today's orders across two stores via a STUB LLM with audit rows under the real
tool names, teardown verified complete (namespace, rows, registrations, tools,
PVs).

**Hard-won lessons (each verified live):**
- wp-setup (post-install hook) creates the woo-secrets Secret woo-mcp needs to
  START, so installs run WITHOUT --wait/--atomic (the main chart's documented
  gotcha); readiness is cluster-derived (WP AND woo-mcp Available).
- helm --timeout applies to HOOK jobs even without --wait: wp-setup needs up to
  ~13 min on the loaded node; helm's 5m default failed post-install hooks that
  were still succeeding. provisioner.helmTimeout now wires it (1140s local).
- The advisory-lock SELECT broke alembic commits (ADR-061, fixed).
- helm --force cannot replace bound PVCs (immutable spec): redrive (release
  not deployed) uninstalls first (PVCs keep-annotated survive), then
  reinstalls.
- The provisioning budget is PER ATTEMPT: a retry resets the namespace
  created-at clock (otherwise an old clock insta-fails healthy retries).
- The DELETING label goes on FIRST (a crash mid-teardown must resume deleting,
  not resurrect the store).
- A queued task (waiting on the concurrency gate) reports "provisioning", not
  "gone" (no false Failed while waiting its turn).
- The store chart needs the wp-setup -> WordPress ingress rule (the main chart
  allows same-namespace pods; the store copy missed it) and the API-server
  egress BOTH on the service CIDR (10.96.0.0/12) and the node CIDR (ClusterIP
  traffic is DNAT-ed to a node IP) - otherwise the hook cannot write
  woo-secrets and silently degrades.
- helm renders values.yaml ints >= 1e6 as float64 scientific notation
  (5.24288e+06): the store chart's IMAGE_MAX_BYTES now goes through `int`.
- The store chart MUST use the main release's resolved image repos (values-local
  rewrites repos to node-local urumi/...): the chart forwards them as env and
  the provisioner --sets them into the store release.
- The 2-core kind node fits ONE store provisioning at a time next to the full
  main stack (maxConcurrent=1 locally; smaller per-store requests; the brief
  sanctions this on a laptop).

**Known trade-offs.** The provisioner holds a cluster-scoped ClusterRole (RBAC
cannot filter namespaces by label; the code-level managed-label guard is the
mitigation, THREAT_MODEL documents the residual). Store provisioning is slow on
a laptop (wp-setup ~5-13 min); budgets are generous locally (1200s). The store
chart is a manual port of the main chart's store components - drift is
possible; the images are forwarded so they always match.

## 2026-10-21: hosted MCP servers (ADR-062)

**What changed.** Admin adds an MCP server BY CONTAINER IMAGE (dashboard
"Hosted servers" page). The provisioner deploys a dedicated namespace
hosted-<name> via plain K8s API objects (no helm needed for four resources):
Deployment (non-root uid 1000, read-only root filesystem, NO service-account
token, tmp emptyDir, mandatory requests/limits capped by Helm values, TCP
probes on the admin port), Service, env Secret (values; the gateway persists
only NAMES and no API ever returns them), and NetworkPolicies (default-deny;
ingress ONLY from gateway pods; egress DNS only). Image rules: a tag or digest
is REQUIRED, :latest refused, plus an optional registry prefix allowlist
(hostedServers.allowedRegistries, empty = any). On Ready the gateway's sync
registers an INTERNAL upstream (slug = name, URL http://<name>.hosted-<name>.svc:
<port>/mcp) so tools appear as <name>__* and permissions/rate-limits/audit work
unchanged. Removal deletes the namespace and the registration. Flag
hostedServers.enabled defaults FALSE (true only in values-local).

**Why.** Reuses the phase-5 pattern (provisioner owns the cluster; the gateway
enforces roles; state derived from the cluster). Applies are idempotent and
fast, so no async task machinery was needed - the objects are the state.

**Live proof (BUILD_LOG phase 6):** demo-mcp-time hosted as "time2" -> Ready,
tools time2__get_current_time/convert_time discovered, MCP tools/call 200 with
real time data; delete -> namespace gone, registration removed, tools gone.

**Two lessons (both fixed live):** (1) the gateway EGRESS allowlist (ADR-045)
blocks new upstream classes by design - hosted servers needed their own
namespace-labeled egress rule, exactly like the store woo-mcp rule; (2) the
upstream URL must carry the /mcp PATH - a pathless URL POSTs to / (405). The
sync now re-asserts the registration for Ready rows (self-heal) so URL-pattern
fixes propagate without manual DB surgery.

## 2026-10-21: OAuth on the gateway (ADR-063)

**What changed.** The MCP endpoint accepts OAuth 2.1 bearer tokens alongside
API keys (which keep working unchanged). Minimal-correct spec implementation
behind oauth.enabled (default FALSE everywhere; true only in values-local for
the live gate):
- RFC 9728 protected-resource metadata + RFC 8414 AS metadata (ingress routes
  /.well-known/oauth-* to the gateway; the dashboard nginx keeps 404ing them)
- RFC 7591 dynamic client registration: public clients only
  (token_endpoint_auth_method=none), redirect_uris stored as EXACT strings
- authorization code flow, PKCE S256 ONLY (plain refused, wrong verifier
  refused), single-use 10-minute codes stored as SHA-256 hashes
- RFC 8707 resource indicator binding: authorize requires resource == the
  canonical <public_base>/mcp; tokens carry it; /mcp refuses foreign-resource
  tokens
- opaque access tokens (5 min) + refresh tokens (7 days, ROTATING); reuse of a
  rotated refresh token revokes the WHOLE family (stolen-token detection);
  /oauth/revoke (RFC 7009 shape) revokes a token or its family
- the BROWSER part reuses the dashboard login (session) + a consent page;
  approving POSTs back with CSRF protection
- every unauthenticated /mcp 401 carries WWW-Authenticate pointing at the
  resource metadata so MCP clients self-discover the flow
- tokens map to a gateway USER: the /mcp path treats them exactly like API
  keys (permissions, per-USER rate limits - OAuth calls carry no API key so
  the default key budget applies - and audit rows attribute to the user)

**Why.** The MCP spec requires OAuth for HTTP transports; the demo keeps API
keys as the simple path. Opaque tokens (not JWTs) keep revocation immediate
and the implementation boring. Refresh rotation + family revocation covers
token theft; hashes at rest cover DB leakage.

**Live proof:** scripts/phase7-oauth-gate.sh (15/15 PASS: 401 pointer, both
metadata docs, DCR, consent, PKCE exchange, /mcp tools/list 29 + tools/call,
refresh rotation, family revocation) AND scripts/phase7_sdk_oauth_client.py
(the MCP Python SDK's OWN OAuthClientProvider: initialize + 29 tools + a tool
call with zero manual token handling) -> SDK-OAUTH-CLIENT: OK.

**Known trade-offs (see THREAT_MODEL):** no client secrets (public clients
only - fine for MCP's localhost clients); consent revocation UI is a follow-up
(tokens can be revoked via /oauth/revoke and the DB today); the resource URI
is the DASHBOARD host (MCP clients reach the gateway through the dashboard
ingress) - prod should use a dedicated gateway host.

## 2026-10-23: per-store TLS via cert-manager HTTP-01 (ADR-064)

**What changed.** Prod multi-store now gives every store its OWN certificate
instead of assuming a wildcard. The main chart grew stores.tls.enabled +
stores.tls.clusterIssuer (default off/empty; committed values stay false), the
provisioner Deployment forwards them as STORE_TLS_ENABLED /
STORE_TLS_CLUSTER_ISSUER (deployment-provisioner.yaml), provisioner Settings
grew store_tls_enabled/store_tls_cluster_issuer, and install_store now also
--sets global.tlsEnabled + ingress.clusterIssuer on every store release. The
store Ingress renders the cert-manager.io/cluster-issuer annotation (issuer
NAME from ingress.clusterIssuer, merged over ingress.annotations - the
dedicated value wins) and a tls block with the store host and its own
secretName <slug>-store-tls, replacing the hardcoded
secretName: urumi-store-wildcard (a wildcard secret nobody can issue here).
The misleading "wildcard TLS" comments in helm/values.yaml and the store
Ingress template now state the real posture: a wildcard DNS RECORD is fine
(*.stores.<domain> -> VPS IP), a wildcard CERTIFICATE is not.

**Why per-store HTTP-01 instead of wildcard.** The VPS DNS host has no API, so
DNS-01 is unavailable - and DNS-01 is the only ACME challenge that can issue
wildcard certificates. A wildcard secret would also put the SAME private key
into every store namespace (copy = more blast radius). Per-store HTTP-01
certificates are automatic (issued + renewed by cert-manager), the secret
stays in the store namespace, and the issuer switches staging/prod by values
only. Trade-off: more Certificate objects and Let's Encrypt rate limits
(50/week/domain) - noise at stores.globalMax=3.

**Alternatives rejected.** (1) Wildcard via DNS-01: needs a DNS API the host
does not offer. (2) Shared wildcard Secret copied into store namespaces: same
DNS-01 blocker + one private key across all namespaces. (3) Out-of-band
operator-issued certs: manual renewal, drift risk. (4) cert-manager Issuer per
store namespace: more RBAC than one cluster-issuer for zero gain.

**NetworkPolicy.** The store chart now renders <slug>-allow-acme-solver when
global.tlsEnabled (mirroring the main chart's ADR-051 policy): ONLY the
ingress-nginx namespace may reach solver pods (label
acme.cert-manager.io/http01-solver), ONLY on the solver port
(networkPolicy.acmeSolver.port, default 8089). Without it, the store
namespace's default-deny would block the solver pod and every store
CertificateRequest would hang until timeout (exactly the failure observed
live in urumi before ADR-051). The storefront allow rule now reads
networkPolicy.ingressNamespace instead of a hardcoded ingress-nginx (default
unchanged), giving the store chart a single controller-namespace source.

**Flags-off identity guarantee.** With stores.tls disabled the rendered main
AND store charts are byte-identical to the pre-change baseline (verified:
normalized `helm template` diff empty; only randAlphaNum secret churn, which
a control re-run on unmodified main reproduces), so committed prod/local
values change nothing.

## 2026-10-23: provisioner image in the GHCR push pipeline (ADR-065)

**What changed.** scripts/push-images.sh now builds and pushes the 9th image,
the provisioner (ghcr.io/<owner>/provisioner:<appVersion>-<sha>), next to the
other eight. Its Dockerfile COPYs the STORE CHART into /charts/store, and
Docker cannot COPY outside the build context, so the script stages helm/store
into src/provisioner/chart exactly like the existing `provisioner-image`
Makefile target, builds with buildx for PLATFORMS (default linux/amd64),
pushes, and verifies the remote platform with `docker buildx imagetools
inspect` like every other image (a tag that lost its amd64 layer fails the
run). An EXIT trap ALWAYS removes the staging dir - on success AND on any
failure (`set -eu`) - so the transient chart copy can never survive a broken
run; src/provisioner/chart is also gitignored as belt-and-braces. The
per-image platform check was factored into verify_platforms() so the
provisioner block reuses it.

**Why.** The VPS pulls every chart-deployed image from ghcr.io/<owner>/
(values-prod pins PUSHED_SHA tags); the provisioner was the only one missing,
so a VPS install with stores enabled could not pull it at all. Pinning
provisioner.image.tag alongside the other images is documented in
values-prod.example.yaml (committed values stay generic).

**Alternatives rejected.** `helm pull`/OCI chart at RUNTIME: needs internet
egress from the provisioner pod (its NetworkPolicy allows API+DNS only) and a
chart/image version skew. Build arg pointing outside the context: Docker
cannot COPY outside the context. Mounting the chart at deploy time (PVC/host
path): new volume plumbing on the VPS for no benefit.

## 2026-10-23: store images stay public GHCR packages (ADR-066)

**What changed.** Nothing in code - this records the PROD posture decision:
fresh store-<slug> namespaces get NO imagePullSecret. The store chart
supports imagePullSecrets (values + urumi.imagePullSecrets helper) and the
provisioner deliberately does not set any; prod keeps the GHCR packages
public.

**Why.** The custom images hold no secrets - proven per image by
scripts/smoke-images.sh (secret-like-file scan inside every image) - so
public packages are the documented default posture (helm/values.yaml,
DEPLOY_VPS.md). Public pulls make ImagePullBackOff structurally impossible in
a fresh namespace and need zero extra RBAC or code.

**Alternatives.** (1) Provisioner copies the docker-registry Secret from the
gateway namespace into every store-<slug> namespace at creation
(stores.imagePullSecret value): feasible - the ClusterRole already grants
secrets:create, the label guard scopes writes - but rejected: it duplicates
the pull token into every store namespace (more places to leak a credential)
and adds code+config for zero confidentiality gain, since the images contain
nothing to protect. (2) Operator manually creates the Secret per namespace:
stores stay broken until someone remembers. Chosen: public packages; revisit
only if private packages ever become a requirement.

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


## 2026-10-22: Landing page rebuilt to docs/LANDING_DESIGN.md as the single source of truth (ADR-086)

**What changed.** Full rebuild of `src/landing/` to the new spec (the spec file landed as
commit 1fb69a8 and overrides the older token note): the new token family (near-black
canvas #040804, surface bands, hairlines, one micro shadow, mint-teal accent), 18
sections in the spec's order, and the full motion set. Self-hosted fonts: Inter Variable
and DM Mono installed from the fontsource packages in a temp folder OUTSIDE the repo,
only the latin woff2 files copied in (48KB + 15KB + 15KB), the two main files preloaded,
`font-display: swap`, licences recorded in docs/FONT_CREDITS.md. The hero graphic ("the
gateway prism") is original inline SVG: client cards, /mcp hub with accent ring and
3s pulse, four upstream cards incl. a dashed "your server", tilted translucent planes
that follow the pointer, curved paths with accent outgoing / violet returning packets,
upstream flash on arrival, drifting tool chips; the loop pauses off screen and on hidden
tabs and renders a static frame under prefers-reduced-motion. Interactions: typing
terminal (28ms/char, 5s loop), client tabs (Cursor / Claude Code / MCP Inspector) with
per-snippet copy buttons and 160ms cross fade, count-up stats with a drawing sparkline,
audit rows streaming every 2.5s (last 5, pause on hover), card spotlight on pointer
devices, 40s marquee paused on hover, the "Break it yourself" simulation (kill pod ->
Unreachable after 600ms with the other servers still answering, restarting after 6s,
Connected again after restart; disable pulls tools from the combined list with the live
count; revoke -> 401 until a new key is issued; Reset restores), step track drawing on
scroll, numbered diagram lighting 400ms apart with a Replay pill, bottom-centre toasts,
nav blur after 8px, mobile menu sheet, entrance reveals staggered 60ms. Light/dark with
the manual toggle; reduced motion shows final values with loops disabled. No framework,
no build step, no external requests.

**Kept, per the brief.** The nginx image pattern and headers (CSP unchanged: `font-src
'self'` already covered fonts; only the cache regex gained `woff2`), all Helm files
untouched, the features.js contract (every beyond-the-brief item `enabled: false`,
`gatewayUrl`, `storeProductCount`, `videoUrl`), the real gateway URL derivation
(`dashboard.<apex>/mcp`), the visible `Bearer <your-api-key>` placeholder (escaped this
time; raw angle brackets are parser-swallowed, see ADR-085), and the copy buttons.

**Deviations.** Each is listed in docs/LANDING_DESIGN.md section 13: dark `muted`
darkened to `#8B8E89` because the spec value fails WCAG AA below 24px (3.9:1 canvas,
3.3:1 surface); light theme completed (white cards on `#EEF2F0` bands, dark danger/warn
tokens); new `on-deep` token for text on accent-deep fills; the sim caption names real
checks (`make test`, `scripts/verify-server-tools.mjs`) because `scripts/regress-core.sh`
does not exist; the client-tabs config block lives under the three steps; the closing
band gained one small line so `storeProductCount` stays wired.

**Verification.** `docker build -t urumi/landing:0.2.0 src/landing` + the container run
from ADR-084. scripts/landing-verify.mjs extended and green: zero external requests, zero
console errors at every width, no horizontal scroll at 375/768/1024/1440, 59/59 AA pairs
in both themes, sticky nav with the scrolled backdrop, reduced-motion gates (packets
hidden, marquee stopped, final stat values, terminal/diagram final states), the full
simulation state machine, clipboard round-trips for all three snippets plus tool chips,
tab switching, budgets from real response bodies (total 196KB of the 350KB budget, JS
31.9KB of 40KB, fonts 78KB), screenshots at 1440/390 in both themes and 6 hero frames
600ms apart with six distinct hashes. Scripted probes (no image input this session):
packets move with both spec colours, hub pulse, marquee motion, streaming rows, terminal
typing, track draw, diagram replay restart (12 -> 1 -> 12), spotlight variables, toasts,
announcement persistence, mobile sheet, tab switch. `helm lint` 0 failures; flag-off
`helm template` renders zero landing lines; values-local renders the landing resources.

**Known trade-offs.** The hero graphic begins just below the fold at 1440x900 (y=1008);
its packets intentionally stay paused until it is scrolled into view, which is the spec's
off-screen pause. This session's model has NO image input, so the screenshots and frames
were not visually reviewed here; scripted geometry and motion probes substitute, and the
visual pass is the top item for Manav in docs/REVIEW_NEEDED_LANDING.md.


## 2026-10-22: Landing nav fix pass: hidden-attribute overrides, the invisible pills, and the packets that never painted (ADR-087)

**User report.** (1) The mobile menu list rendered open on desktop widths from page load and
pushed the page down. (2) The primary pill "View on GitHub" had nearly invisible text in both
themes.

**Root causes, verified in the browser before fixing (not assumed).** (1) Author `display`
rules beat the UA `[hidden] { display: none }` cascade: `.nav-sheet { display: grid }` and
`.btn { display: inline-flex }` made the hidden sheet (314px, sticky under the nav) and the
hidden `#simIssue` render anyway, at every width, from load. (2) Inside that always-open
sheet, `.nav-sheet a { color: var(--body) }` (specificity 0,1,1) overrode `.btn-primary`
(0,1,0): the GitHub pill painted `#A8ABA6` on `#E3E5E1` in dark (1.75:1) and near-black on
near-black in light. The user saw the sheet's pill; the nav's own pill measured fine.
(3) Found during the pass: the hero packets never painted at all. CSS
`.hv-packets circle { opacity: 0 }` overrode the per-frame `opacity` ATTRIBUTE (CSS rules beat
presentation attributes), so the previous "6 distinct frame hashes" motion evidence came from
chip drift and the hub pulse, not packets.

**Fixes.** (1) Global `[hidden] { display: none !important }` guard. (2) The sheet became a
full-screen overlay rendered ONLY below 900px (`@media (min-width: 900px)` hides it
unconditionally): fade+slide 300ms, close button, Escape, link-choice and resize-to-desktop
routes, body scroll lock, focus trapped inside, focus returns to the menu button, correct
aria-expanded/controls/labels. (3) The sheet link rule is now scoped to `.sheet-links a`, so
the pills inside keep their token colors. The nav was rebuilt desktop-first per the brief:
original SVG logomark + wordmark left, the five section links in one translucent pill group
centre with a sliding accent-deep highlight driven by a section IntersectionObserver
(band -40%/-52%), repositioned on resize and after webfont swap; right: secondary pill,
primary pill with a hover-nudging arrow, round theme toggle; 64px bar shrinking to 56px
after 8px of scroll with blurred translucent canvas and hairline border. Hero fixes from the
same brief: dashed connection lines restyled to a dedicated `--flow-line` token (alpha 0.34
dark / 0.38 light, width 2), packets now paint with a halo trail circle (r 8 at 30 percent)
per packet, the two tilted planes are smaller (452x228 / 358x158) and fainter (opacity
0.32 / 0.26), and the hero was tightened so the graphic starts 46 percent into a 1440x900
viewport at load (was 0 percent: it began below the fold), while 390px still shows the
headline, buttons and the terminal card.

**Verification.** scripts/landing-verify.mjs grew gates for every point above: the sheet is
hidden and takes zero space on load at 375/768/1024/1440, content starts directly under the
bar, the desktop bar is 64px, the menu opens and closes by every route (button, Escape,
close button, section link with scroll, resize to desktop), focus stays trapped across 12
tabs, the body scroll locks, focus returns to the toggle, pills inside the OPEN sheet pass
contrast in both themes, the scroll-spy highlights security and kubernetes with the glide
pixel-exact under the active link (204px = 204px), reduced motion disables the glide
transition while keeping it positioned, dismissing the announcement does not break the
sticky offset, the hero graphic is >=45 percent visible at 1440x900, the mobile hero shows
headline/buttons/card, packets actually paint (max opacity 1.0, halos == cores), planes
<=0.35 opacity and line alpha >=0.25. Full suite: LANDING VERIFY PASSED, 63/63 contrast
pairs per theme, budgets total 204,633B of 358,400B and JS 36,471B of 40,960B. Pixel probes
substituted for eyes (this model has no image input): the six new hero frames contain
78-179 teal packet pixels each and violet return pixels in three of six frames; the nav pill
regions in both full-page shots show a 221/230 luminance spread, i.e. text painting.

**Known trade-offs.** The bar shrink animates height (one element, cheap) rather than
transform because the brief asked for a literal 64px-to-56px transition. The smooth-scroll
spy legitimately walks the highlight through sections while a long scroll settles; the
verify gate uses instant scrolling for determinism. Screenshots and frames were retaken and
the open-sheet states saved for Manav, but the visual review is still his: see
docs/REVIEW_NEEDED_LANDING.md.


## 2026-10-23: One repo URL for every landing link, injected from the chart (ADR-088)

**What changed.** Every outbound link on the landing page is now built at runtime instead of
hardcoded. The GitHub repo URL lives in ONE value: `landing.repoUrl` in the chart values
(defaulted in the committed values.yaml to https://github.com/manavmax/urumi-mcp-gateway).
A new `urumi-landing-config` ConfigMap renders a tiny `landing-config.js` from that value
plus the chart's existing ingress hosts (dashboard/store, scheme from `global.tlsEnabled`:
https when TLS is on, http locally) and is mounted over the image default of the same path
in the landing Deployment, so deployments change links from values without a rebuild. The
image ships a matching default `landing-config.js` (the only page-side copy, needed for
plain `docker run` previews); nginx serves it no-cache so ConfigMap changes reach browsers.
features.js now ships `repoUrl: ""` and index.html carries no URL: the six repo-root links
keep `data-repo` and the ten docs links carry `data-repo-path="<in-repo path>"`, resolved by
main.js to `<repoUrl>/blob/main/<path>`. Chart.yaml `home` was updated to the same repo.
The `dashboard.example.com` placeholders in the config snippets became the neutral
`dashboard.<apex>` form. GitHub links keep `target="_blank" rel="noopener noreferrer"`;
dashboard and store links stay same-tab, built from the chart hosts (in-cluster) or derived
from the page host (docker preview), with no signup/OAuth/registration links anywhere.

**Why.** All 16 link targets in the page source pointed at a stale org
(github.com/urumi-ai/mcp-gateway) and were scattered across 16 hardcoded hrefs plus
features.js; the blob links also pinned the `landing` branch instead of `main`.

**Verification.** scripts/landing-verify.mjs gained a links block that prints every distinct
rendered href and gates: all 16 GitHub hrefs start with the manavmax repo prefix, zero stale
org/placeholder links, GitHub links carry target/rel while site links stay same-tab, and
every `/blob/main/<path>` href is cross-checked against `git ls-tree -r main --name-only`
(all five paths exist). Rendered: 6 repo-root links, 5 dashboard links, 2 store links, 10
docs links over 5 distinct main paths. helm renders the ConfigMap with
`http://dashboard.127.0.0.1.nip.io` for values-local and `https://dashboard.<host>` for a
prod-like overlay (https + real hosts); helm lint 0 failures; flag-off template still renders
zero landing lines. Full landing suite PASSED with budgets total 205,019B and JS 37,413B.
Secret/placeholder scan of src/landing and the helm landing files: no credentials, no emails;
the only URL defaults are the allowed GitHub repo URL. Pre-existing chart-wide placeholders
outside the landing scope (nip.io local hosts, example.com in values-prod.example.yaml and
the wp adminEmail default) were reviewed and left untouched.

## 2026-10-22: Store v2 - invented brand, one niche, 36-product catalog (ADR-070)

**Decision.** The store layer (branch store-v2) stops being generic "everyday
goods" merch and becomes a coherent fictional brand: **Loam & Ember**, a
slow-made home-and-desk goods store. Six categories: Ceramics, Textiles, Candles
& Care, Desk & Paper, Kitchen, Carry. 36 products seeded from a rewritten
`store/products.json` (single source of truth, ADR-037), every one with title,
short + long description, regular price, SKU (`LOAM-*`), stock quantity with
manage-stock on, weight + dimensions, tags, one main image plus 2-3 gallery
images, ~7 on sale, 2 out of stock, 6 featured, 6 marked new, and 5 variable
products (size or colour) whose variations carry their own SKU, price and stock.
Idempotent by SKU exactly as before: running the seed twice creates nothing,
resets nothing.

**Why.** The demo video needs a believable store, and "Urumi" is the project's
name, not a shop identity. An invented brand keeps the project name free for
the gateway/dashboard while the storefront reads like a real (fictional) shop.
Name checked to be a made-up word pair, no real store, logo or copy used
anywhere.

**Migration.** Old `URUMI-*` products are NOT deleted by the seed (idempotent,
SKU-create-only by design). They fall out of the live catalog via
`make demo-reset`, whose keep-manifest (ADR-073) is regenerated to the new SKUs;
on a fresh install only the new catalog exists.

## 2026-10-22: wp-setup seed extended in ONE file (helm wp-setup job template) (ADR-071)

**Decision.** Supporting the full product model (sale prices, manage-stock +
out-of-stock, weight/dimensions, tags, gallery sideloads, variable products
with per-variation SKU/price/stock) required changes to the seed PHP, which
lives inline in `helm/templates/jobs/wp-setup.yaml`. Per the task brief ("if a
wp-setup change is unavoidable, keep it in one file and say so") ALL wp-setup
changes for store v2 live in that ONE file and nowhere else in helm/: the seed
section is extended field-by-field, idempotency semantics are unchanged
(SKU lookup; created=kept=0 on second run; force mode never deletes), and the
About/Shipping page copy plus site title line were updated for the new brand in
the same file. Nothing else in helm/ is touched; src/gateway, src/dashboard,
src/woo-mcp untouched.

**Why.** There is no hook: the seed runs `wp eval-file /tmp/seed_products.php`
with a fixed path, and the store-assets image cannot teach the job new calls.
Alternatives were worse: seeding-on-request from a mu-plugin makes the first
page load of the demo video nondeterministic and can trip PHP timeouts; a
second "extended seed" invoked by nothing is dead code. One surgical edit to
the file the job already runs, verified by timing (see ADR-075), keeps the
guarantee that `helm upgrade` finishes setup in about 3 minutes.

**Verification.** The exact rendered script runs in a compose harness
(artifacts/store-compose, gitignored) against the same hardened images the
cluster uses; seed timing is measured (36 products, ~150 sideloads) and the
seed-twice count equality is asserted by the verification harness.

## 2026-10-22: Original generated artwork only; no third-party images (ADR-072)

**Decision.** Every store image is original artwork produced by
`scripts/gen-store-images.py` (Pillow) - flat illustrated product renders in
the established style: consistent light direction, soft contact shadow, tile
backgrounds from the theme palette. Main + gallery variants per SKU (main,
alt-angle/scene, detail) and a transparent cutout for hero/category tiles.
PNG at 1000px (longest side), flat art compresses far below the 120KB/file
budget; total catalog images stay under the 12MB budget. No CC0 downloads, no
photos of people, no external URLs at runtime (images ship inside the
store-assets image and are sideloaded from local files by the seed, ADR-038).
docs/IMAGE_CREDITS.md records that all files are original generated artwork
with per-file listing generated by the tool.

**Why.** Sourcing 100+ third-party photos with verifiable licenses for a
public repo is a review burden and a takedown risk; the established generator
style (ADR-037) already looks consistent, compresses well, and keeps the store
100% offline-capable.

## 2026-10-22: demo-reset keep-manifest regenerated for the 36-product catalog (ADR-073)

**Decision.** `scripts/demo-seeds.json` (the auditable keep/delete manifest for
`make demo-reset`, ADR-032) is regenerated to list the new catalog's parent
SKUs (LOAM-*) with their names, prices and types (simple/variable), and
`scripts/demo-reset-media.php` keeps not only featured images but also every
gallery image listed in store/products.json, so a reset keeps the full catalog
+ media and removes only orders and non-manifest test products (including the
legacy URUMI-* products). No other demo-reset behaviour changes.

**Why.** demo-reset deletes any product NOT in the manifest; leaving the old
12-SKU manifest would delete the new catalog on the next reset. The media
rule ("thumbnail of a kept product") would delete every gallery attachment the
new seed creates. Both scripts already read store/products.json as the source
of truth; this keeps the three files (products.json, seeds manifest, seed
section) from drifting.

## 2026-10-22: Design tokens kept and refined; one earthy accent (ADR-074)

**Decision.** The redesign KEEPS the existing theme.json token family - page
`#ECEBE7`, card `#FFFFFF`, tile `#F3F2EF`, ink `#14171C`, muted `#5F6673`,
hairline, radius scale 12/24/40/999, shadow scale, Instrument Serif display +
Inter body - and REFINES it: one earthy accent **clay `#A0522D`** (deep
terracotta, 4.7:1 on white) for sale badges, sale prices and small emphasis
marks; two new category tints (sage `#D8E0D4`, clay-soft `#EBD9CC`) joining the
existing four so six categories each get a tint; dusk gradient hero kept.
Final tokens, type scale and spacing are documented in docs/STORE_DESIGN.md.
Contrast gate (rest/hover/focus) must pass after every change.

**Why.** The brief says keep existing tokens and refine, not replace; the
accent gives the premium-minimal warmth the style direction asks for without
introducing a second brand system.

## 2026-10-22: Verification harness and docs for store v2 (ADR-075)

**Decision.** Verification runs against a THROWAWAY docker compose stack
(artifacts/store-compose, gitignored) using the exact hardened images the
cluster runs for this commit, with wp-setup executed as the REAL script
rendered from the helm template (helm template only - no cluster, no kubectl,
no helm install, never touching main). `scripts/verify-store-v2.mjs` (new,
store tooling) drives Playwright screenshots (1440 + 390), zero-third-party and
console-error gates, page weight, an e2e COD checkout whose order is confirmed
via the Woo REST API, and REST catalog assertions (count, images, sale,
out-of-stock, weight/dims, tags, variations with own stock). In-cluster
verification commands that were NOT run are written to docs/STORE_VERIFY.md.
Secrets for the harness live in artifacts/store-compose/.env (chmod 600,
gitignored) and are never printed; a dedicated compose-only REST key is created
for verification and never committed.

**Why.** The kind cluster is off-limits (another session owns it), and the
brief asks for real runs, not prose. Matching images + the rendered job script
gives fidelity to the in-cluster wp-setup path while staying fully local.

## 2026-10-22: Generated artwork retired; photo-first catalogue (ADR-076)

**Decision.** All 155 generated PNGs and scripts/gen-store-images.py are
deleted (git rm). The storefront moves to real photography per
docs/STORE_DESIGN.md (alpha, the single source of truth): warm neutral tokens,
sharp corners, no accent colour, no illustrations. store/images keeps a
.gitkeep so the store-assets image build does not break while photos are
curated. The wp-setup seed's sideload step already skips image files that are
absent on disk, so the store seeds and functions during the interim: 36
products, zero images, neutral beige/dark placeholders in the theme.

**Why.** The brief retires the previous look explicitly; generated flat art
reads as "AI-looking artwork" against the new gallery-like direction. A blind
fill of placeholder photos would violate the "never pad with weak photos"
rule, so the catalogue rebuild waits for curated photos (ADR-078).

## 2026-10-22: Self-hosted Newsreader + Hanken Grotesk variable fonts (ADR-077)

**Decision.** The theme ships latin-subset variable woff2 files only:
newsreader-latin-wght-normal.woff2, newsreader-latin-wght-italic.woff2,
hanken-grotesk-latin-wght-normal.woff2, installed from
@fontsource-variable/newsreader@5.3.0 and @fontsource-variable/hanken-grotesk
@5.3.0 via npm into a temp folder OUTSIDE the repo, then copied in. Licences
(SIL OFL 1.1, copyright lines) recorded in docs/FONT_CREDITS.md. theme.json
declares both families with font-display: swap; functions.php preloads both
woff2 files. No CDN, no external font requests at runtime.

**Why.** The reference fonts (Plantin Infant, Monument Grotesk) are commercial
and cannot ship; Newsreader and Hanken Grotesk match the measured type scale
and are OFL licensed. Latin-only subsets keep the store-assets image small.

## 2026-10-22: Unsplash sourcing machinery, curation deferred (ADR-078)

**Decision.** Photo sourcing uses the Unsplash API (per the source override in
the brief) through scripts/fetch-unsplash.py: the Access Key is read only
inside the script, never printed, echoed, logged or written anywhere; search
responses are cached in artifacts/store-photos/cache/ (gitignored) so re-runs
do not burn the 50 req/h demo budget; candidate previews are downloaded from
the CDN (uncounted) into candidate sheets (scripts/sheet-candidates.py) for
eyeball curation. scripts/process-photos.py implements the full pipeline for
AFTER curation: download_location ping per chosen photo, raw fetch at w=1600,
4:5 centre crop to 960x1200, webp q80 with a hard 150KB ceiling (q stepped
down to 60), detail-crop gallery images, artifacts manifest +
docs/IMAGE_CREDITS.md writer and a contact sheet. The 600px variant is a
WordPress-derived size (urumi-600, registered in functions.php) so srcset
serves 480x600 next to the 1200px master without double-shipping files.

**IMPORTANT (honesty note):** this session's model could not view images (the
read tool rejects image input for this model). Per the brief ("if you cannot
[view images], build everything except the photo selection, say so at the top
of your report, and stop. Do not pick photos blindly"), NO photos were chosen,
no products were renamed for photos, and no screenshot was eyeballed. Ten
cached searches (30 results each) and candidate sheets wait in
artifacts/store-photos/ for a photo-capable pass or for Manav.

**Why.** The brief's quality bar (reject faces, text, logos, clutter,
inconsistent style) is a visual judgement; guessing would ship weak photos and
product copy that does not match what the photographs show.

## 2026-10-22: Seed defaults to .webp; demo-seeds regenerator (ADR-079)

**Decision.** In the ONE wp-setup file (ADR-071 pattern), the seed's image
fallback filename changes from <SKU>.png to <SKU>.webp to match the photo
pipeline output. scripts/regen-demo-seeds.py regenerates scripts/demo-seeds.json
from store/products.json (parent SKU, name, price, type) so the demo-reset
keep-manifest can never drift after the catalogue is rebuilt from photos. The
regenerated output was verified byte-equivalent (modulo key order and note
wording) to the committed manifest, so the committed file is left untouched
until the rebuild.

**Why.** One-line seed change keeps the idempotent path untouched (verified:
second run created=0 kept=36); the regenerator removes the manual step most
likely to be forgotten during the photo rebuild.

## 2026-10-22: Theme rebuilt to the gallery spec; AA outranks the muted token (ADR-080)

**Decision.** store/theme/urumi-store is rebuilt to docs/STORE_DESIGN.md:
theme.json tokens (canvas #FBFBF9, surface-alt bands, ink #262525, radius 0,
no shadows, hairline #E1E1E0, the two variable families), a rewritten
assets/styles.css (outline/solid/text buttons, 44px inputs with ink focus and
the rgb(235,235,235) inner shadow, 4:5 tile frames with 500ms 1.03 zoom,
plain-text flags, vertical PDP thumbnails, hairline tables, surface-alt
summaries and footer, mobile full-screen menu overlay with 300ms fade,
reduced-motion kill switch, 4/3/2 responsive grids), new header (wordmark,
Shop, Collections dropdown, About, Shipping, Search, Account, Cart) and footer
(four columns, demo-store line, "Photography from Unsplash." link to
/image-credits/), new front-page pattern order (hero, intro, collections,
new-and-featured, editorial split, details strip) with the faq/newsletter/
trust/split patterns deleted. Two deliberate deviations from the letter of the
token table, both logged here: (1) struck-through old prices and "Sold out"
flags use neutral-4 #4C4C4C instead of neutral-1 #999999 because #999999 on
canvas is 2.75:1 and fails the WCAG gate the brief demands; (2) the
photo-absent hero ground is the dark warm neutral #5C5142 (not taupe) so the
white hero copy passes AA before photographs exist; a real photo covers it
fully and the 20 percent veil sits on top. html/body use overflow-x: clip so
the off-canvas Woo mini-cart drawer can never widen the page. Verified in the
compose harness: 91/93 harness checks pass (2 known cosmetic Woo ResizeObserver
console warnings on the block cart), WCAG gate passes all rest/hover/focus
samples, e2e COD checkout green, seed-twice idempotent, demo-reset contract
holds (36 KEEP, 0 planned product deletions).

**Why.** The spec's own contrast requirement ("contrast AA verified") is a
gate; when a muted token and AA conflict, AA wins and the deviation is
recorded rather than silently bent.

## 2026-10-22: Credits manifest ships in the store-assets image (ADR-081)

**Decision.** store/photos-manifest.json (committed; regenerated by
scripts/process-photos.py) carries one row per shipped photograph (file, SKU,
Unsplash photo id, photographer, photographer URL, photo URL, licence
"Unsplash License", one-line verdict). It is COPY'd into the store-assets
image and copied onto wp-content by the same initContainer step (one added
cp line in the chart's store-assets args, same ADR-038 semantics). The
wp-setup seed (still the ONE file, ADR-071) creates the /image-credits/ page
if missing; the theme's functions.php renders the page content from the
manifest via the_content filter, with an honest "credits being finalized"
line while the manifest is empty. The footer line "Photography from
Unsplash." links to /image-credits/. docs/IMAGE_CREDITS.md is rewritten to
describe the Unsplash pipeline and to state plainly that no photograph has
been chosen yet (ADR-078).

**Why.** The brief requires a footer credit line linking to real credits; a
page rendered from a committed manifest keeps credits in sync with the shipped
image without a second seeding path, and makes the curation pass purely
mechanical: run the pipeline, commit the manifest, rebuild the image.

## 2026-10-23: Photo pass applied; catalogue cut to 29 products (ADR-082)

**Decision.** The reviewer's sheet selections (artifacts/store-photos/choices.json,
gitignored) are applied verbatim: hero = lifestyle 08 (backup lifestyle 02, held for
the contrast gate), editorial = lifestyle 04, six category banners, and 29 product
photos - every chosen photo used exactly once (38 unique Unsplash photo ids; banner
photos are never product photos; flagship products get the first photo of their
category list). The catalogue is cut from 36 to 29 products because the photo
selection cannot fill every product honestly. Exactly these 7 products are REMOVED
(live-store migration: a fresh seed never creates them; the regenerated
scripts/demo-seeds.json keep-manifest, ADR-073, makes the next `make demo-reset`
delete them from the live store along with their orphaned media):

- LOAM-CER-005 Stoneware Teapot - no teapot photograph exists in the reviewer's
  ceramics selection (mug/bowl/vase sheets only); showing another ceramic as a
  teapot would break the "never show a different product than the one named" rule.
- LOAM-CER-006 Spoon Rest - same: no spoon-rest photo; it was also one of the two
  out-of-stock products, so the catalogue no longer carries a sold-out example.
- LOAM-CND-004 Hand Soap Bar and LOAM-CND-006 Incense Holder - the candle pool has
  exactly 4 usable photos (5 selected minus the banner) and the brief caps candles
  at 3-4 products; the two jar candles and the scent-line extras (wax melts, room
  mist) keep the strongest photo-product fit.
- LOAM-DSK-003 Pencil Pouch and LOAM-DSK-004 Desk Tray - the desk pool has only 3
  product photos after the banner (4 selected minus the banner), and all desk
  photos are cropped to the notebook/pen area per the reviewer note; a waxed-canvas
  pouch and an ash tray have no matching content in them.
- LOAM-DSK-006 Letter Writing Set - the third desk drop (only 3 desk photos); it
  was the other out-of-stock product.

The wp-setup seed needs no code change for the removal: it creates exactly what
products.json lists. Desk photos carry a 1.3x centre zoom crop (and the desk banner
a tighter wide crop) to obey "crop to notebook/pen only; crop out laptops, earbuds,
phones" - applied blind (that pass could not view images) and flagged for an eyeball
check on artifacts/store-photos/contact-sheet-products.png. products.json now
references <SKU>.webp + one <SKU>-2.webp detail crop per product, carries the
hero/editorial entries, and each category carries "image": banner-<slug>.webp.
verify-store-v2.mjs's out-of-stock check is now catalog-driven (live OOS SKUs must
equal products.json OOS SKUs) instead of requiring >= 1 OOS product, which the cut
made false.

**Why.** Every removed product is one the reviewer's selection cannot photograph
honestly; filling the gaps by reusing photos would break the one-photo-once rule
and the "never show a different product" design rule. 29 products sits inside the
28-32 target with 6 variable, 6 featured, 6 new and 4 on-sale products.

## 2026-10-23: Category banners ship as files + one theme block (ADR-083)

**Decision.** Each products.json category carries "image": banner-<slug>.webp
(processed wide crop, 1600x640 target, <=220KB, gitignored choices -> committed
manifest/credits). A new dynamic block urumi-store/category-banner renders it at
the top of taxonomy-product_cat.html (align full, eager, honest alt from the
catalog), falling back to the previous archive head when a category has no image
file. No seed change: like the hero and editorial photos, banners are read from
wp-content/store/images/ files by the theme, so they ship entirely inside the
store-assets image (ADR-081 path). Theme version bumped to 3.1.0 for cache
busting; the store-assets image keeps its 0.1.0 local tag (import + pod restart
lands the new content, per the Makefile comment).

**Why.** The six banners are static files, so the one-image, one-file theme
pattern (hero/editorial) extends with zero new seeding or REST surface; the
idempotent seed contract stays untouched.

## 2026-10-24: Store chart seeded to parity + a drift guard over both seed copies (ADR-084)

**Decision.** The per-store chart (helm/store, baked into the provisioner
image at /charts/store) had been frozen at the pre-store-v2 wp-setup since
Phase 5 while the main chart got the whole v2 rewrite. A store provisioned with
the frozen chart + the v2 catalog created all 29 products but assigned none:
the old seed resolved a product's category by NAME while products.json
references categories by SLUG, so the lookup was always empty and every
product stayed in "Uncategorized" with count=0 collection pages (reproduced on
kind before the fix; the /image-credits/ page also 404'd because the page and
the photos-manifest copy were both missing). The fix copies the main chart's
seed + storefront blocks into helm/store byte-for-byte: wp-setup.yaml and
deployment-wordpress.yaml are now IDENTICAL between the two charts; every
store-specific difference (hostnames, secrets, namespaces, quotas, resource
requests) lives in values/other templates, untouched. A drift guard -
scripts/check-store-chart-parity.py, wired into `make lint` (chart-parity
target) and `make test` - extracts the seeding blocks from both charts,
normalizes whitespace, and fails with a unified diff when they differ; the only
escape hatch is an explicit ALLOWLIST in the script (empty today) for genuinely
store-specific lines. How to update it is documented in the script docstring.

**Why.** Duplicating the seed in two charts was accepted at Phase 5 because
the provisioner image must carry its own chart and the main release must stay
self-contained - but nothing checked the copies against each other, so v2
work on the main chart silently bypassed the store chart and only surfaced on
a live provisioned store. The guard makes any future divergence fail `make
lint` instead of shipping. The later option remains the proper fix: extract the
seed script and the store-assets copy into ONE shared file (helm library chart
or a file rendered into both charts / baked into an image) so the duplication
disappears; that touches the provisioner image build and both charts, so it is
deliberately deferred, and until then this guard is the contract.
