# Urumi Gateway Dashboard Design Spec (STAGE 0, revised 0.6)

Status: **proposal only**. No `src/dashboard` or backend code was modified to produce this document.
Mockups: `design/mockups/{login,overview,servers,members,audit,chat,palette-options}.html` (static, self-contained, sample data),
plus `design/mockups/logo-options.html` and `design/mockups/favicon.svg`. Logo A is final (decided STAGE 0.5, reconfirmed 0.6).

## 0. Ground rules (from the brief)

1. **Only real, backend-backed data.** Every number maps to an existing endpoint or a proposed one
   (sections 3 and 4). No credit cards, goals, followers, upgrade panels, fake avatars or photos.
   Avatars are initials on soft tint circles.
2. **Status is never colour alone.** Every status badge pairs colour with an icon and text.
3. **No new runtime dependency.** Mockups are static HTML, inline CSS, hand-rolled inline SVG,
   system fonts, no CDN. PNGs are rendered with the existing `playwright-core` devDep.
4. **No long dashes in UI copy.** No em dashes and no en dashes appear in any visible string in the
   mockups, this document, or `docs/DECISIONS.md`. Ranges use the word "to"; clauses use commas,
   colons or periods. Short hyphens inside words ("read-only") are fine. Re-verify with a grep for
   the em dash and en dash characters before any UI text ships.
5. **Gradient used sparingly, only where it earns attention.** The full rule is in section 1.1.
6. PNG renders live in `design/mockups/png/` and are **not** committed (gitignored).

## 1. Design tokens (STAGE 0.6)

Pattern: a neutral warm-greige canvas, white cards floating on it, near-black ink as the only
primary, and gradient used sparingly in exactly five sanctioned places. Nothing else in the UI
carries colour except the small semantic status tints and the chart tints.

### 1.1 Colour

| Token | Value | Use | Contrast |
|---|---|---|---|
| `--bg` | `#ECEBE7` | warm greige page canvas | - |
| `--surface` | `#FFFFFF` | cards, sidebar pill, form panel | - |
| `--surface-2` | `#F4F3EF` | inner wells, hover washes | ink on it 16.18:1 |
| `--tint-soft` | `#F1F0EC` | soft pill highlight, hover wash on white | ink on it: 15.7:1 |
| `--hairline` | `rgba(20,23,28,.07)` | dividers, table rules, input outlines: nearly invisible | decorative only |
| `--text` / ink | `#14171C` | primary ink, primary buttons, active nav fill | 17.96:1 on white |
| `--text-muted` | `#5F6673` | labels, captions | 5.78:1 on white, 4.84:1 on greige: passes AA normal text |
| `--ink-hover` | `#2A2E35` | ink button and nav hover | 14.5:1 on white |
| `--periwinkle` | `#B9C4DD` | soft chart bars, accent tint, focus rings | ink on it 10.27:1 |
| `--peach` | `#EFCBBE` | gradient stop, accent tint | ink on it 11.94:1 |
| `--ok-bg` / `--ok-text` | `#DDEDE4` / `#2F5D46` | Connected badge (mint) | 6.24:1 |
| `--bad-bg` / `--bad-text` | `#F4DCD8` / `#8A3B33` | Unreachable badge, errors (blush) | 5.84:1 |
| `--off-bg` / `--off-text` | `#E9E8E3` / `#565D69` | Disabled badge (grey) | 5.41:1 |
| `--butter` / `--lilac` / `--sky` / `--sand` | `#F3E6C4` / `#E4DEF1` / `#DCE7F3` / `#EADFCB` | icon tiles, avatar tints, suggestion-card tints | ink on all: 13.6:1 to 14.8:1 |

**Primary action and active nav** are the near-black ink pill: `#14171C` fill, white text, a subtle
top highlight (`inset 0 1px 0 rgba(255,255,255,.18)`), hover `#2A2E35`. There are **no coloured
primary buttons** anywhere. White on ink measures 17.96:1.

**Gradient rule.** Gradient is allowed **only** on:
(a) ONE hero stat tile per page,
(b) the half-ring gauge or main chart fill (very soft),
(c) the login art panel,
(d) the chat empty-state glow and avatar chips,
(e) the soft background glow behind the page edge.
Never on buttons, table rows, badges or every card. Text on gradients is always dark ink
`#14171C`; every stop of every option measures at or above 9.18:1 (table below).

**Gradient options** (rendered side by side in `design/mockups/palette-options.html`, swapped via
one `--grad` CSS variable; the other mockups ship with A as the working default until the final
choice is made):

| Option | Stops | Ink on stops (WCAG, sRGB) | Character |
|---|---|---|---|
| A "Dusk" (working default, recommended) | periwinkle `#B9C4DD`, lilac `#D9C8DC`, peach `#EFCBBE` | 10.27:1, 11.33:1, 11.94:1 | equal distance from the mint and blush semantic badges; clearly visible on the greige so the hero anchors the page |
| B "Mist" | slate blue `#A9BBD3`, sky `#CFE0EE`, cream `#F3EAD8` | 9.18:1, 13.30:1, 15.03:1 | calmest, closest to the neutral system, but the cream stop nearly disappears on the greige |
| C "Rose sand" | dusty rose `#E3BFB8`, sand `#EADFCB`, pale blue `#D5E0EC` | 10.62:1, 13.61:1, 13.43:1 | warmest; the rose stop leans on the Unreachable blush tint, watch badge semantics |

Measured pairs (script-computed, sRGB relative luminance): ink `#14171C` on white 17.96:1; on
greige `#ECEBE7` 15.06:1; muted `#5F6673` on white 5.78:1 and on greige 4.84:1 (both pass AA for
normal text, closing the contrast flag from revision 0.5); Disabled text `#565D69` on `#E9E8E3` 5.41:1 (passes
AA, supersedes the 0.5 trade-off note); Connected 6.24:1; Unreachable 5.84:1; white on ink 17.96:1.

### 1.2 Radii, shadows, spacing, type

| Group | Tokens |
|---|---|
| Radii | card `24px`, inner chips and wells `14px`, pill `999px`, sidebar `32px` |
| Shadows | card `0 1px 2px rgba(20,23,28,.04), 0 10px 30px rgba(20,23,28,.05)`; popover `0 2px 4px rgba(20,23,28,.05), 0 16px 40px rgba(20,23,28,.10)`; hover adds slightly more lift, never a hard shadow |
| Borders | cards and popovers have **no visible border**; inputs and tables keep the nearly invisible hairline where separation is needed |
| Spacing | 20px grid: `20px` gaps between cards, `24px` inner card padding, 8px micro-rhythm inside components |
| Type scale | 11 / 12 / 13 / 14 / 16 / 20 / 28 (page title) / display numeral 36 |
| Fonts | system stack `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`; mono `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` |
| Numerals | semibold, `letter-spacing:-.02em`, `font-variant-numeric:tabular-nums`, small grey label above |

### 1.3 Motion tokens

| Token | Value | Use |
|---|---|---|
| `--dur-fast` | `150ms` | hovers, presses, focus rings |
| `--dur-mid` | `300ms` | card and row entrances, pop, tooltip |
| `--dur-slow` | `700ms` | counters, chart draw and sweep |
| `--dur-rail` | `260ms` | sidebar pill expand/collapse width only |
| `--ease` | `cubic-bezier(.2,.8,.2,1)` | default gentle easing |
| `--ease-spring` | `cubic-bezier(.34,1.56,.64,1)` | toggle switches only |
| `--stagger` | `40ms` | default per-item delay; sidebar labels use 20ms |

Only `transform`, `opacity`, `stroke-dashoffset` and (on the sidebar overlay only) `width` are
animated, so nothing shifts layout. Section 6 lists every animation and its reduced-motion state.

## 2. Component inventory

| Component | Description / states | Data |
|---|---|---|
| Logo mark | rounded square, arch (doorway), horizontal line through the arch; logo A is final; `#i-logo` symbol, 21px in the ink circle, 28px on chat empty state, 40px on login | static |
| Wordmark | "Urumi" semibold, tight letter spacing, small "Gateway" label; shown when the sidebar expands and on login | static |
| Sidebar | floating white pill, overlay expansion; full spec in section 2.1 | `/api/me` |
| Bottom nav (720px and below) | fixed 5-icon tab bar, no pill on mobile | static |
| Stat tile | white card, muted label above, semibold tabular numeral, delta pill; lifts 2px on hover; the hero variant carries the gradient | per section 3 |
| Hero stat tile | ONE per page, gradient background (option A by default), dark ink text, white delta pill | per section 3 |
| Chart card | white card, hand-rolled SVG bars/lines/gauge with `role="img"` and `title`; soft periwinkle bars, blush error caps, gradient allowed on today's bar or gauge fill; floating white mini-cards inside showing values with small delta pills | per section 3 |
| Half-ring gauge | 180 degree arc, soft gradient fill on a greige track, ink value in the centre | success rate |
| Chip / badge | small semantic tint pill, **icon + text**: mint / blush / grey / neutral / sky | enum fields |
| Status badge | Connected (mint, check, breathing dot) / Unreachable (blush, x, one-time shake) / Unknown (neutral, dot) / Disabled (grey, pause, static) | `Server.status` |
| Table | hairline row dividers, mono for slugs, URLs and keys, hover wash with a left accent bar, staggered fade-in (first 12); reflows to labelled cards at 720px; gradient never on rows | list endpoints |
| Toggle switch | ink on / neutral off, springy slide, admin only | `Server.enabled` |
| Buttons | primary = ink pill with top highlight, presses down 1px; secondary = white with hairline ring; ghost; danger ghost (blush text) | - |
| Inputs / select / search | pill, hairline ring, focus ring; the header search pill ends in a round ink search button | - |
| Round icon buttons | white circles with the card shadow, only for actions that really do something | - |
| Skeleton | shimmer sweep in a pastel tint, never a spinner | loading state |
| Empty state | logo-derived shapes, floating arch loop; chat has its own glow pattern | empty list |
| Key reveal | slides down, key text types in, "shown once" note highlights once | POST `/api/keys` |
| Chat thread | user and assistant bubbles, tool-call chips that pop in staggered, typing indicator with three bouncing dots | SSE events |
| Suggestion cards | small white cards with soft tinted icon tiles, real prompt examples | static copy |
| Composer | wide pill, soft outline, text field, round ink send button; no attach, mic, settings or upgrade controls | SSE request state |
| Chat history panel | white card, radius 24, search field, past chats (title, preview, time ago), "New chat" ink pill | **ND** (localStorage later) |
| Modal | add or edit server, revoke key confirmations (spec only) | mutations |
| Avatar | initials circle, tint background | `User.email` |
| Banner / alert | inline info and error slots | - |

### 2.1 Sidebar (floating pill, STAGE 0.6)

- A floating white vertical pill, inset `16px` from the top, left and bottom page edges, radius
  `32px`, card shadow, icon-only and about `72px` wide when collapsed.
- Icons are simple 1.75px line icons, inline SVG: Overview, Servers, Members and Keys, Audit, Chat.
- **Active item: a filled ink circle with a white icon.** No coloured active states.
- Bottom of the collapsed pill: avatar circle and a sign-out icon.
- On hover (80ms intent delay) or keyboard focus-within, the pill expands to about `248px` as an
  **overlay on top of the content**; the content margin never changes, so nothing reflows or
  shifts. Expansion animates `width` only, `260ms` with the `--ease` token.
- Labels fade in and slide 8px from the left with a 20ms stagger per item, starting 70ms after the
  hover begins, so they arrive while the pill is still opening.
- The expanded state shows: the ink logo mark with the "Urumi / Gateway" wordmark at the top,
  labelled items with a soft `--tint-soft` pill highlight behind the active row, and at the bottom
  a user card (initials avatar, email, role) on a soft gradient glass background plus a Sign out
  row.
- The pill collapses 150ms after the pointer leaves (the base transition carries a 150ms delay;
  hover replaces it with the 80ms intent delay).
- Reduced motion: expansion is instant, no stagger, no width travel visible; global reduce rules
  zero durations and delays.
- Mobile (720px and below): no pill, the bottom tab bar takes over.
- Both states are rendered to PNG; `?expanded=1` forces the expanded state for the mock
  (`overview-expanded-1440.png`).

## 3. Pages: widget to data source

Legend: **E** = existing endpoint (no backend work), **N** = **new endpoint required**,
**ND** = new scope, needs decision.

### 3.1 Login (`design/mockups/login.html`)

| Widget | Source | Status |
|---|---|---|
| Full-page soft gradient glow background (sanctioned gradient use c) with drifting pastel shapes | static inline CSS + SVG | E (none) |
| Large white rounded card (radius 24), logo A with wordmark, "Sign in" heading, labelled email and password fields, ink primary button, footer "Access is managed by your administrator" | form state | E |
| Sign in submit | `POST /api/auth/login`, session cookie and CSRF token | E |
| Inline error slot (401 detail), shown via `?error=1` | login response | E |
| Mobile (390px) | same single-column card; tagline hidden | static |
| Remember me / SSO / password reset | - | **ND** |

### 3.2 Overview (`design/mockups/overview.html`, bento grid like reference 1)

Page header: greeting "Hello, Admin" with a one-line subtitle, a pill search field with a round ink
search button, and round white icon buttons only for actions that really do something (account
menu). A slim controls row carries the SAMPLE tag, the auto-refresh pulse, the Day / Week / Month
segmented switch (ink active pill) and the Motion toggle.

| Widget | Source | Status |
|---|---|---|
| Row 1, tile 1 (gradient hero): Tool calls, 7 days, count-up, delta pill | `GET /api/stats`, `audit.calls` | **N** |
| Row 1, tile 2: Success rate with a mini bar sparkline and error count | `GET /api/stats`, `audit.success_rate`, `by_outcome` | **N** |
| Row 1, tile 3: p95 latency with a line squiggle and delta | `GET /api/stats`, `audit.p95_ms` | **N** |
| Row 1, tile 4: Servers connected with an icon in a soft tinted circle | `GET /api/servers`, count by status | E |
| Row 2, card 1: Tool calls per day, 14-day bar chart, floating white mini-cards with success rate and p95 values and small delta pills | `GET /api/stats?range=14d`, `audit.per_day[]` | **N** |
| Row 2, card 2: half-ring gauge, success rate, soft gradient fill | `GET /api/stats`, `audit.success_rate` | **N** |
| Row 2, card 3: My account: initials avatar, role chip, active key count, manage link | `GET /api/me`, `GET /api/keys` | E |
| Row 3, card 1: Recent activity list, thin vertical accent bar per row, time under each line, outcome chip and duration | `GET /api/audit?limit=8` | E |
| Row 3, card 2: Tools overview: tools exposed per server, warning chip on the failing server | `GET /api/tools` | E |
| Row 3, card 3: Fleet status: connected / unreachable / disabled chips plus the two problem servers | `GET /api/servers` | E |
| Security posture strip | static copy | E (none) |
| Skeleton shimmer demo and empty-state loop (motion documentation) | loading / empty states | E |
| Global search behaviour | - | **ND** |

### 3.3 Servers (`design/mockups/servers.html`, admin + member variants)

| Widget | Source | Status |
|---|---|---|
| Summary chips (connected / unreachable / unknown / disabled counts) | `GET /api/servers`, client-side count | E |
| Server table: slug, URL, status badge, enabled, tools, actions | `GET /api/servers` | E |
| Per-server tools expand | `GET /api/tools`, grouped by `server_slug` or `<slug>__` prefix | E |
| Enabled toggle (ink), add, edit, delete (ink primary where primary) | `POST /api/servers/{id}/disable` and `/enable`, `POST /api/servers`, `PATCH`, `DELETE` (admin) | E |
| Member variant | read-only table plus "only admins can modify servers" note; controls hidden | E |
| Health-check-now button, latency history chart | - | **ND** |

### 3.4 Members and Keys (`design/mockups/members.html`, admin + member variants)

| Widget | Source | Status |
|---|---|---|
| Users table: email, role chip, active, actions | `GET /api/users` (admin only) | E |
| Invite form | `POST /api/users` | E |
| Delete user | `DELETE /api/users/{id}` (self-delete blocked server-side) | E |
| Keys table with owner column | `GET /api/keys` joined with `GET /api/users` (admin) | E |
| Create key, key reveal with copy, revoke | `POST /api/keys`, `DELETE /api/keys/{id}` | E |
| Member variant | own keys only, no users table | E |
| Key expiry, key usage, per-user key creation UI | fields exist, no usage tracking | **ND** |

### 3.5 Audit (`design/mockups/audit.html`)

| Widget | Source | Status |
|---|---|---|
| Filters: server, tool, outcome, time range, user (admin) | existing `GET /api/audit` query parameters | E |
| Day / Week / Month segmented switch | sets `from` / `to` | E |
| Table: time, user, server, tool, outcome chip, duration, request id | `GET /api/audit` | E |
| Total and "showing X to Y", Prev / Next pagination | `total`, `limit`, `offset` | E |
| Member variant | user filter hidden, own rows only | E |
| CSV export (current page or streaming) | - | **ND** |
| Outcome trend chart, row detail drawer | - | **ND** / **N** if shipped |

### 3.6 Chat (`design/mockups/chat.html`, pattern from reference 2)

| Widget | Source | Status |
|---|---|---|
| Centered empty state: logo-derived soft gradient glow shape (sanctioned use d), "Hello, Admin" heading, "What would you like to do in your store?" subtitle | static copy | E (none) |
| Three suggestion cards with soft tinted icon tiles: "What orders came in today", "Create a product", "What time is it in Tokyo" | static sample copy | E (none) |
| Composer: wide pill with soft outline, text field, round ink send button; no attach, mic, settings or upgrade controls | `POST /api/chat/completions` | E |
| Tool-call chips stay readable and animated as before (shown via `?thread=1`) | SSE `tool_call` events | E |
| Right-hand Chat history panel (radius 24): search field, past chats with title, one-line preview, time ago, "New chat" ink pill at the bottom | - | **ND** (localStorage now, `GET/POST /api/chats` only if rejected) |
| "Serving: model" chip | SSE `model` event | E |
| Multi-turn context, auth note | client re-sends thread each turn; credentials never reach the browser | E |

## 4. New endpoints required (summary)

| Endpoint | Purpose | Consumers | Notes |
|---|---|---|---|
| `GET /api/stats` | Overview aggregates: `servers.by_status`, `tools_exposed`, `audit.{calls,success_rate,by_outcome,p50_ms,p95_ms,per_day[]}`, `users_total` (admin only) | Overview, Audit trend | Read-only; `per_day` counts by day for the requested range. Percentiles from `duration_ms`. Members get `users_total` omitted and an `own_keys_active` count instead. |
| *optional* `GET /api/chats`, `POST /api/chats` | chat history persistence | Chat history panel | **ND**, only if localStorage is rejected |

All other server, user, key, audit and chat mutations already exist and enforce CSRF and RBAC.

## 5. "Needs decision" list (new scope, not committed)

| Feature | Options | Blocking? |
|---|---|---|
| Gradient option A / B / C | user chooses; mockups ship with A as the working default | Yes for Stage 1 tokens |
| Chat history persistence | localStorage only versus new tables plus endpoints | Yes for Chat history panel |
| CSV export | client-side current page versus server streaming | Yes for Audit button |
| Dark mode | second token set; mockups ship light only | No |
| Global search behaviour | filter current page / jump to Servers / new endpoint | No |
| Key expiry plus "create key for user" UI | fields exist, FE must send them | No |
| Member Overview visibility | members see servers, tools, own audit rows and keys | No |
| Health check on demand plus latency history | new endpoint and background probe | No |

## 6. Motion

Pure CSS plus small vanilla JS; every duration and easing comes from section 1.3.

### 6.1 Page and layout

| Animation | Where | Timing |
|---|---|---|
| Cards fade and rise 8px, staggered 40ms | every page | 300ms ease-out |
| Table rows fade in staggered, first 12 only | Servers, Members, Audit | 300ms, 40ms apart |
| Row hover lifts to a wash with a left accent bar | all tables | 150ms |

### 6.2 Sidebar (the only width animation in the system)

| Animation | Timing |
|---|---|
| Hover intent delay before expansion | 80ms |
| Expand: `width` 72px to 248px, overlay, content does not reflow | 260ms `--ease` |
| Labels: fade plus 8px slide, 20ms stagger per item | from 70ms after hover starts |
| Collapse after the pointer leaves | 150ms delay, then 260ms |
| Reduced motion | instant expand, no stagger, delays zeroed |

### 6.3 Tiles, numbers, charts

| Animation | Where | Timing |
|---|---|---|
| Stat tiles count up from 0 to the exact value | Overview and Members counts | 700ms, ends on the real value |
| Delta pills pop in after the counter | stat footers, floating mini-cards | 300ms, 600ms delay |
| Tiles lift 2px on hover | `.card.stat:hover` | 300ms |
| Bars grow with stagger; today's bar and the gauge sweep | Overview chart and gauge | 700ms, 30ms apart |
| Lines draw via `stroke-dashoffset` | squiggle sparklines | 700ms |
| Hover a bar: highlight, dim others, tooltip with exact value and date | charts | 150ms |
| Live pulse dot | Overview controls row | 2.4s breathing loop |
| Skeleton shimmer, never a spinner | loading states | 1.4s loop |

### 6.4 Status and feedback

| Animation | Where | Timing |
|---|---|---|
| Connected badge dot breathes | every Connected chip | 2.8s loop |
| Unreachable one-time shake | Unreachable chips | 450ms once |
| Disabled static | Disabled chips | none |
| Toggle switch spring | Servers enabled toggles | 300ms spring |
| Buttons press down 1px | all buttons | 150ms |
| Copy button swaps to check with a pop | Members copy key | 300ms |
| Key reveal: slide, type-in, note highlight | Members | 300ms / 400ms / 1.4s |
| Chat: messages slide up, tool chips pop in staggered, typing dots bounce | Chat thread | 300ms, 70ms apart; dots 1.2s loop |
| Chat empty-state glow breathes | Chat empty state | 6s loop |
| Login: drifting pastel shapes, card fades up | Login | 28 to 44s drift, 700ms card |
| Background page-edge glow and empty-state glow breathe very slowly | Overview, Chat | 6s loop |

### 6.5 Guardrails (must hold in Stage 1)

- **`prefers-reduced-motion: reduce` disables every animation** and shows final values
  immediately: durations collapse to 0.01ms, delays (including the sidebar intent and stagger
  delays) and iterations are removed, counters jump to the exact value, chart lines and segments
  render at their final state. The mockups expose a `Motion: on/off` control and `?rm=1`;
  `overview-reduced-1440.png` is rendered with Playwright's `reducedMotion: "reduce"` emulation.
- Only `transform`, `opacity`, `stroke-dashoffset` animate, plus `width` on the sidebar overlay
  alone. Nothing else shifts layout.
- Nothing delays access to data by more than 700ms.
- The only infinite loops: live pulse dot, Connected breathing dot, typing dots, empty-state and
  background-glow breathing, login shape drift. The only springy easing is the toggle switch.
- Counters always end on the exact real value; Stage 1 animates real data only.
- Motion tokens live in `:root` so the whole system changes in one place.

## 7. Logo

Logo A is final (STAGE 0.5 decision, reconfirmed for 0.6): the arch fills about 40 percent of the
rounded square, the line passes through the arch opening, 5.5px corner radius. The filled knockout
variant lives in `design/mockups/favicon.svg`. Colours: ink `#14171C` on light surfaces, white on
the ink circle. The comparison page `design/mockups/logo-options.html` is kept for the record.

## 8. Responsive behaviour

- **Desktop (1080px and above, mockup rendered at 1440):** floating pill sidebar collapsed at 72px,
  content margin 104px, bento rows 4 / 3 / 3 columns, chart row `1.7fr / .95fr / .85fr`.
- **Tablet (721 to 1120px):** bento reflows to 2 columns, floating mini-cards become static.
- **Mobile (720px and below, mockup rendered at 390):** no pill, bottom tab bar; single-column
  bento; tables reflow to labelled cards; the chat history panel stacks below the thread; the
  login tagline hides; the sidebar never appears.

## 9. Accessibility notes

- All chart SVGs: `role="img"` plus a `title` and a text legend (never colour only).
- Focus-visible rings on every interactive element; the sidebar expands on focus-within too.
- Chips: icon plus text, all pairs at or above 4.5:1 (see the table in 1.1; nothing is flagged).
- Inputs have explicit labels; the account menu is reachable by keyboard.
- Every animation honours `prefers-reduced-motion`, including the sidebar expansion; see 6.5.
- Dashboard status indicators pair colour with an icon and text, never colour alone.

## 10. What the mockups deliberately do not show

Goal or engagement radars, revenue attribution, credit-card art, upgrade prompts, streak counters,
fake avatars or photos: nothing without a backing field in this system. SAMPLE data shows layout
and density only, and every page carries a visible SAMPLE tag.

