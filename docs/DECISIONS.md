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
4. The removed Members sentence was the expiry dev note; the create flow sets no expiry, so the
   keys table keeps showing "never" and no expiry UI was implied.


