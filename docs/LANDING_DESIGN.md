---
version: alpha
name: Urumi Gateway Dark
description: |
  A dark, technical, developer-facing landing page for a team MCP gateway that runs
  on Kubernetes. A near-black canvas, off-white pill buttons, hairline borders and a
  single mint-teal accent create a calm, premium infrastructure feel. The page is
  alive: a layered hero graphic with packets flowing through the gateway, a typing
  terminal, live-streaming audit rows, count-up numbers, and small interactive
  simulations (kill a server, revoke a key) that show the product's behaviour. Depth
  comes from surface colour, hairlines and one micro shadow, never from heavy effects.
source:
  note: "Design language derived from two analysed reference design files. Tokens are reused with small tweaks. No name, logo, copy, illustration or hero artwork of the reference site is used. All graphics are original."
colors:
  canvas: "#040804"
  surface: "#1A1C19"
  surface-alt: "#131412"
  surface-raised: "#2C2E2B"
  ink: "#E3E5E1"
  body: "#A8ABA6"
  muted: "#6C6E6A"
  faint: "#4B4D4A"
  hairline: "rgba(255,255,255,0.05)"
  hairline-strong: "rgba(255,255,255,0.10)"
  accent: "#14B8A6"
  accent-bright: "#5EEAD4"
  accent-soft: "#99F6E4"
  accent-deep: "#0B3B36"
  decor-violet: "#A78BFA"
  decor-violet-deep: "#2A2250"
  danger: "#FF5B5B"
  warn: "#F5B454"
  # TWEAK: the reference uses a lime or green accent family. We shift it to mint-teal.
  # Every accent lives in a CSS variable, so the whole page can be re-hued in one place.
typography:
  display: { fontFamily: "Inter Variable", fontSize: 45px, fontWeight: 500, lineHeight: 1.07, letterSpacing: -0.45px }
  heading-md: { fontFamily: "Inter Variable", fontSize: 38px, fontWeight: 500, lineHeight: 1.16, letterSpacing: -0.38px }
  heading-sm: { fontFamily: "Inter Variable", fontSize: 18px, fontWeight: 400, lineHeight: 1.33 }
  heading-xs: { fontFamily: "Inter Variable", fontSize: 15px, fontWeight: 400, lineHeight: 1.47, letterSpacing: 0.15px }
  quote: { fontFamily: "Inter Variable", fontSize: 28px, fontWeight: 400, lineHeight: 1.29 }
  body-md: { fontFamily: "Inter Variable", fontSize: 16px, fontWeight: 500, lineHeight: 1.5 }
  body-sm: { fontFamily: "Inter Variable", fontSize: 14px, fontWeight: 500, lineHeight: 1.43 }
  body-xs: { fontFamily: "Inter Variable", fontSize: 13px, fontWeight: 500, lineHeight: 1.54, letterSpacing: 0.39px }
  caption: { fontFamily: "Inter Variable", fontSize: 11px, fontWeight: 400, lineHeight: 1.6, letterSpacing: 0.1px }
  code-sm: { fontFamily: "DM Mono", fontSize: 12px, fontWeight: 400, lineHeight: 1.67, letterSpacing: 0.36px }
  code-md: { fontFamily: "DM Mono", fontSize: 14px, fontWeight: 400, lineHeight: 1.7 }
  # TWEAK: the reference font ABC Diatype is a commercial typeface and cannot be shipped.
  # Inter and DM Mono are OFL licensed and are self-hosted as woff2 files (latin subset only).
rounded: { none: 0px, xs: 5px, sm: 7px, md: 10px, lg: 12px, full: 9999px }
spacing: { xxs: 4px, xs: 8px, sm: 12px, md: 16px, lg: 20px, xl: 24px, xxl: 28px, xxxl: 32px, section: 40px, band: 44px }
section-padding-y: "clamp(72px, 10vw, 144px)"
shadows:
  micro: "rgba(4,8,4,0.4) 0 1px 3px 0, rgba(4,8,4,0.5) 0 2px 32px 0"
  inset: "rgba(0,0,0,0.05) 0 0 0 1px inset"
  glow-accent: "0 0 0 1px rgba(94,234,212,0.25), 0 0 40px rgba(20,184,166,0.18)"
motion:
  duration: { fast: 160ms, base: 240ms, slow: 600ms, scene: 1200ms }
  easing: { standard: "cubic-bezier(0.2, 0.7, 0.2, 1)", soft: "cubic-bezier(0.4, 0, 0.2, 1)" }
themes:
  dark: { bg: "#040804", surface: "#1A1C19", surfaceRaised: "#2C2E2B", text: "#E3E5E1", textMuted: "#A8ABA6", border: "rgba(255,255,255,0.05)", accent: "#14B8A6", accentFg: "#04100E", focusRing: "#5EEAD4" }
  light: { bg: "#F9FDFB", surface: "#EFF3F1", surfaceRaised: "#E8EBE9", text: "#111915", textMuted: "#686E6C", border: "#D6DAD8", accent: "#0F766E", accentFg: "#FFFFFF", focusRing: "#14B8A6" }
components:
  button-primary: { backgroundColor: "{colors.ink}", textColor: "#101810", rounded: "{rounded.full}", height: 36px, padding: "6px 16px", boxShadow: "{shadows.inset}" }
  button-secondary: { backgroundColor: "rgba(255,255,255,0.05)", textColor: "{colors.ink}", border: "1px solid {colors.hairline-strong}", rounded: "{rounded.full}", height: 36px, padding: "6px 16px" }
  button-large: { backgroundColor: "{colors.surface}", textColor: "{colors.ink}", border: "1px solid {colors.hairline}", rounded: "{rounded.md}", height: 70px, padding: "24px 32px", typography: "{typography.code-sm}", boxShadow: "{shadows.micro}" }
  button-text: { textColor: "{colors.body}", height: 32px, padding: "0 12px", rounded: "{rounded.full}", typography: "{typography.heading-xs}" }
  card: { backgroundColor: "{colors.surface}", border: "1px solid {colors.hairline}", rounded: "{rounded.lg}", boxShadow: "{shadows.micro}", padding: 16px }
  chip: { backgroundColor: "{colors.accent-deep}", textColor: "{colors.accent-bright}", rounded: "{rounded.full}", padding: "4px 10px", typography: "{typography.code-sm}" }
  chip-neutral: { backgroundColor: "rgba(255,255,255,0.05)", textColor: "{colors.body}", border: "1px solid {colors.hairline}", rounded: "{rounded.full}" }
  navigation: { height: 64px, backgroundColor: "transparent", textColor: "{colors.ink}" }
breakpoints:
  - { width: 375, container: 327, paddingX: 24, display: 37 }
  - { width: 768, container: 704, paddingX: 32, display: 37 }
  - { width: 1024, container: 896, paddingX: 64, display: 45 }
  - { width: 1440, container: 1312, paddingX: 64, display: 45 }
---

# Urumi Gateway Dark: landing page design spec

This file is the single source of truth for the landing page in `src/landing/`.
Where this file and an older design note disagree, this file wins.

## 1. Visual theme and atmosphere

Serious, technical and confident, with a playful pulse. The page is calm at rest and
alive on interaction. The canvas is near-black. Hierarchy comes from scale, spacing and
contrast, never from bold weights or heavy shadows. One mint-teal accent marks the few
things that matter: highlighted headline words, links, active chips, the hero graphic
and live data.

Key characteristics:
- Near-black canvas (`#040804`), lifted surfaces (`#1A1C19`), alternating section bands.
- Off-white pill buttons. The accent never fills a primary button.
- Hairline borders at 5 percent white. One micro shadow. Radius 12px on cards, pills on controls.
- Tight negative tracking on display sizes, weight 500 only on display and section headings.
- Monospace (DM Mono) for tool names, URLs, config, logs and small labels.
- Real product visuals (audit log, stat tiles, topology), not abstract illustration.
- Motion is purposeful: it explains data flow and rewards interaction.

## 2. Colour roles and where each is used

- Canvas `#040804`: page background and footer.
- Surface-alt `#131412`: alternate section bands so long pages read in rhythm.
- Surface `#1A1C19`: cards, mockup panels, code blocks. Raised `#2C2E2B`: hover and active.
- Ink `#E3E5E1`: headings, primary button fill. Body `#A8ABA6`: paragraphs. Muted `#6C6E6A`: captions and labels. Faint `#4B4D4A`: placeholders and disabled.
- Accent `#14B8A6` and bright `#5EEAD4`: highlighted headline words, text links, chips, status "Connected", sparkline strokes, outgoing packets in the hero graphic, focus ring.
- Accent-deep `#0B3B36`: chip background, glow base.
- Decor-violet `#A78BFA` and its deep `#2A2250`: decorative only, used for returning packets and a few hero layers. Never on controls or body text.
- Danger `#FF5B5B`: Unreachable, rejected, errors. Warn `#F5B454`: rate limited or degraded. Rare and legible.
- Rules: never put the accent on a primary button fill, never use raw white, never add a second saturated hue to controls.

## 3. Typography

- Inter Variable for all UI and marketing text, DM Mono for code. Both self-hosted (see section 11).
- Display 45px (37px on tablet and below), weight 500, tracking -0.45px. Section headings 38px, weight 500, tracking -0.38px. Sub-titles 18px. Body 16px weight 500 on dark for legibility.
- One highlighted phrase per display headline is set in `accent-bright`. Never more than two words.
- Do not force uppercase. Small mono eyebrow labels above section headings are allowed, set in `muted` with 0.3px tracking.

## 4. Components

- Primary button: ink fill, `#101810` text, 36px high, full pill, inset hairline. Hover lifts 1px and brightens slightly. An arrow glyph slides 3px right on hover.
- Secondary button: transparent or 5 percent white fill, hairline border, ink text.
- Large mono button (used in the closing band for the repo and docs): 70px high, 10px radius, surface fill, micro shadow, DM Mono 12px.
- Text button: body colour, 32px high, hover raises to ink.
- Card: surface fill, hairline border, 12px radius, micro shadow. Hover: border goes to `hairline-strong` and a soft spotlight follows the cursor (section 7).
- Chip: accent-deep fill with accent-bright mono text. Neutral chip for tool names. Clicking a tool chip copies its name and shows a small toast.
- Code block: surface fill, DM Mono 13 to 14px, a copy button top right, tabs above it for client types.
- Focus: a visible 2px ring in `focusRing` with 2px offset. Never remove focus indication.
- Disabled: opacity 0.5 plus a muted fill, never opacity alone.

## 5. Page anatomy: how each section is built and how they continue

Sections alternate between canvas and surface-alt bands, separated by a hairline. Each
section has a mono eyebrow, a heading, a one or two line lead, then content. Section vertical
padding is `clamp(72px, 10vw, 144px)`. Content is centred in a 1312px max container with
64px side padding on desktop, 24px on mobile. All copy below is final unless the repo
disagrees with it, in which case the repo wins.

1. **Announcement bar** (canvas, 36px). "A take-home project, live demo." plus "View the source" link. Dismissible, remembered with try/catch localStorage.
2. **Navigation** (64px, sticky, blurred translucent canvas after 8px scroll). Wordmark "Urumi Gateway" in text, links: How it works, Features, Security, Kubernetes, Docs. Right: secondary pill "Open dashboard", primary pill "View on GitHub", theme toggle. Mobile: menu toggle opening a full-width sheet.
3. **Hero** (canvas). Centred. Display headline: "One MCP endpoint for your *whole team*." (accent on the italic phrase). Lead: "Register your MCP servers once. Give every teammate a key. Their editor and the built-in chat get every tool, while the upstream credentials stay on the server." Buttons: primary "Open dashboard", secondary "View on GitHub". Under it a mono caption: "A take-home project built for the Urumi AI FDE internship, not a product of Urumi." Below the buttons the hero graphic (section 6) at about 560px tall, fading into the next band with a gradient mask. Behind the graphic: a faint dot grid with a radial mask and a soft accent glow.
4. **Built with** (canvas). A quiet row of text marks in muted: Kubernetes, Helm, k3s, FastAPI, PostgreSQL, React, MCP, WooCommerce, cert-manager, nginx. Slow marquee that pauses on hover. Caption: "The stack behind this demo."
5. **Three product blocks** (surface-alt). Heading: "Connect, control, run." Three columns, each a card with a mono label, a title, a one line lead and three bold-title bullets.
   - *Connect*: "One endpoint" (every enabled server's tools behind one MCP URL), "Namespaced tools" (`woo__list_orders`, so names never collide), "Failure isolation" (per-server timeouts and a circuit breaker; one dead server never breaks the rest).
   - *Control*: "Per-user keys" (hashed, shown once, revoked on the next call), "Tool permissions" (hide and reject tools per role), "Audit log" (who, which tool, how long, what happened).
   - *Run*: "One Helm chart" (kind locally, k3s on a VPS, only values change), "Deny by default" (NetworkPolicies, non-root containers), "Safe upgrades" (rollback on failure, data kept).
6. **Three steps** (canvas). Heading: "From zero to a tool call." Numbered 01, 02, 03 on a horizontal track whose line draws on scroll: "Register servers once" (an admin adds each server's URL and credential; the credential is encrypted and never sent to a client), "Issue keys" (invite members; each creates a personal API key), "Use it anywhere" (one URL and one key in an MCP client, or the built-in chat; every call is permission-checked and audited under its caller). Each step has a small live widget: a typing URL field, a key that reveals once then masks, a tool call line.
7. **How a tool call travels** (surface-alt). The animated SVG diagram of section 6, extended: client or chat agent, gateway checks (key, role, rate), routing, upstream server, the store, and the audit row being written. Steps are numbered and light up in sequence on scroll; a "Replay" pill restarts it.
8. **Break it yourself** (canvas). Heading: "Kill a server. Nothing else notices." An interactive simulation (section 7): three server cards (woo, time, notes) with status chips and tool lists, and three controls: "Kill pod", "Disable", "Revoke key". Caption: "A simulation of the real behaviour. The real checks run in scripts/regress-core.sh."
9. **Control** (surface-alt). Two columns. Left: heading "Every call, on the record." with three bullets (revoke a key and the next call is rejected, disable a server and its tools vanish everywhere, restrict a tool and it is hidden and refused). Right: an audit-log table mockup in a card whose rows stream in every 2.5 seconds (sample data, labelled). Columns: time, user, tool, duration, outcome (chips: ok in accent, error in danger, permission denied in warn).
10. **Fleet at a glance** (canvas). Heading: "See the whole fleet." A panel with four stat tiles that count up when scrolled into view (sample data, labelled): tool calls, success rate, p95 latency, servers connected. Under them a wide sparkline area chart that draws left to right. Chips below list failure reasons in plain words (timeout, connection refused, auth rejected).
11. **What runs where** (surface-alt). Heading: "Public, private, and state." Three tier cards with a connecting line: Public (ingress, gateway, dashboard, this page), Private (the MCP servers and the store, reachable only from the gateway), State (Postgres and MariaDB on persistent volumes). A small table below compares values-local and values-prod: hosts, TLS, images, storage.
12. **Security, stated plainly** (canvas). Two columns "A member can" and "A member cannot". Below, six control cards: hashed keys, server-side credentials, SSRF guard, default-deny network, non-root containers, login lockout. Each card has a tiny animated line icon.
13. **From the design notes** (surface-alt). The quote typography, used honestly: three large cards, each a short design statement set at 28px with a link to the doc it comes from. Examples: "Client keys are never forwarded upstream. The gateway uses its own credential." "One dead server never takes down the rest." "Revoking a key takes effect on the very next call." Label the section "From the design notes". These are never presented as testimonials.
14. **Docs cards** (canvas). Three cards with a mono tag and an arrow: System design and tradeoffs, Threat model, Upgrade and rollback. Link to the repo docs.
15. **Beyond the brief** (surface-alt, hidden unless enabled). Rendered only from `features.js` items with `enabled: true`: multi-store provisioning, hosted MCP servers, OAuth, compact tool mode, per-key rate limits, metrics. Never claim an item that is not enabled.
16. **Demo video** (hidden until `landing.videoUrl` is set). A large rounded player frame.
17. **Closing band** (canvas, centred). Heading "See it running." Two large mono buttons: "Open the dashboard" and "View the repository", plus the primary pill "Open the store".
18. **Footer** (canvas, hairline top). Four columns: Explore (Dashboard, Store, GitHub), Docs (README, Design decisions, Threat model, System design), Stack (Kubernetes, Helm, FastAPI, Postgres, React, MCP), Project (the disclaimer). A very large faint wordmark at the bottom that brightens on hover. Small line: "Sample data is labelled. No analytics, no trackers, no external requests."

## 6. Hero graphic specification (original artwork)

Concept: "the gateway prism". All elements are inline SVG plus CSS, no images, drawn originally.
- Left column: three small client cards (Editor, Chat agent, CLI) with mono labels.
- Centre: a rounded-square gateway hub with an accent ring, a faint inner grid and the label `/mcp`. A soft glow pulses every 3 seconds.
- Right column: four upstream cards (woo, time, notes, and a dashed empty card "your server") each with a status dot.
- Layered translucent planes sit behind the hub with a slight perspective tilt (max 6 degrees) that follows the pointer with easing. Layers use `decor-violet-deep` and `accent-deep` with hairline edges.
- Smooth curved SVG paths connect clients to the hub and the hub to upstreams. Small glowing packets travel along the paths: outgoing packets in `accent-bright`, returning packets in `decor-violet`. A packet reaching an upstream makes that card flash once.
- Tool-name chips (`woo__list_orders`, `time__convert_time`, `notes__search_notes`) drift slowly on the planes with parallax.
- A loop of about 8 seconds runs forever. It pauses when the graphic is off screen or the tab is hidden.
- Reduced motion: render a static composed frame with no packets moving.

## 7. Motion and interaction spec

This section is authored for this project. The reference design files do not define motion.

- Entrance: each section's heading, lead and content fade and rise 16px over `slow` with `standard` easing, staggered 60ms, triggered once by IntersectionObserver at 15 percent visibility.
- Hero typing terminal: a card under the lead types, at 28ms per character, a sample prompt "What orders came in today?" then shows a tool call line `woo__list_orders  118 ms  ok` and a two line sample answer. It loops with a 5 second pause. Labelled "sample".
- Client tabs: a tab strip (Cursor, Claude Code, MCP Inspector) above the config block swaps the snippet with a 160ms cross fade. Every snippet has a copy button, with the label flipping to "Copied" for 1.5 seconds. Snippets use a placeholder key and the derived gateway URL, never a real key.
- Count-up: stat tiles count from zero over 1200ms with ease-out when first visible. Sparklines draw with stroke-dashoffset over 1200ms.
- Streaming audit rows: a new row slides in at the top every 2.5 seconds from a small pool of sample events (sample users alice and bob, a mix of ok, error and permission denied), keeping the last 5 rows. Pause on hover.
- Card spotlight: cards set `--mx` and `--my` on pointermove and draw a soft radial highlight behind the content. Pointer devices only.
- Button micro-interactions: lift 1px, arrow slides 3px, 160ms.
- Marquee: the "Built with" row scrolls slowly (40s loop) and pauses on hover.
- "Break it yourself" simulation (client-side only, labelled as a simulation):
  - Kill pod on a server: its status chip changes to Unreachable (danger) after 600ms, its tools dim, a packet sent to it fails with a short shake, while the other two servers keep answering sample calls. After 6 seconds a "restarting" state returns it to Connected.
  - Disable: the server's tools animate out of the combined tool list immediately.
  - Revoke key: a sample request line returns `401 unauthorized` on the next call, in danger colour; "Issue new key" resets it.
  - A "Reset" pill restores the starting state. The combined tool list always shows the correct count for the current state.
- Step track: the line between steps 01 to 03 draws as the section scrolls into view.
- Diagram replay: the numbered steps in section 7 light up in sequence, 400ms apart.
- Toasts: bottom centre, 2 seconds, used by copy actions.
- Navigation: after 8px scroll the bar gets a translucent canvas background with a backdrop blur and a hairline bottom border.
- Performance rules: animate only transform and opacity, no layout thrash, requestAnimationFrame for the hero loop, everything paused off screen and when the tab is hidden.
- Reduced motion: honour `prefers-reduced-motion: reduce` by disabling the hero loop, typing, marquee, streaming rows, count-up and parallax, showing final values and static frames. Content must be fully usable without motion.
- No external requests, no analytics, no tracking. Script and style from self only.

## 8. Depth and elevation

Flat first. Cards use the micro shadow and a 5 percent hairline. Primary buttons use an inset hairline. Nothing larger than a 32px blur. The only glow is the accent glow on the hero hub and the focus ring. No glossy effects, no multi-level shadow stacks.

## 9. Shapes

Pills for every control (buttons, inputs, chips, tabs). Cards 12px. Large mono buttons 10px. Images and mockup screenshots 0 to 10px. Do not mix radii inside one component.

## 10. Responsive behaviour

Tokens in the front matter give the breakpoints. Display text goes 45px to 37px below 1024px. Section padding goes 64px to 32px to 24px. The three-column blocks stack on mobile. The hero graphic switches to a vertical layout (clients on top, hub in the middle, upstreams below) under 768px, with fewer packets. The simulation controls wrap into a two-row grid. The nav collapses into a menu sheet. The page must have no horizontal scroll at 375, 768, 1024 or 1440 px.

## 11. Fonts, licences and assets

- Inter Variable and DM Mono, both under the SIL Open Font License. Install the npm packages `@fontsource-variable/inter` and `@fontsource/dm-mono` in a temporary folder outside the repo, copy only the latin subset woff2 files into `src/landing/fonts/`, preload the two main files, use `font-display: swap`, and record the licences in `docs/FONT_CREDITS.md`.
- No third-party images. All icons and graphics are original inline SVG.
- Budgets: total transfer under 350KB including fonts, JavaScript under 40KB, no layout shift, no external requests.

## 12. Do and do not

Do:
- Keep it dark, spacious and centred on one accent. Use hairlines and spacing for structure.
- Keep every claim true of the repo. Label every mockup as sample data.
- Make interactions optional: the page must read perfectly with motion off.

Do not:
- Copy the reference site's name, logo, copy, illustrations or hero artwork.
- Use the accent as a primary button fill, or add warm accents to controls.
- Use bold headline weights, large shadows, sharp corners or more than one glow.
- Invent customers, logos, testimonials, statistics or reviews.
- Add a framework, a build step, a CDN, analytics or any third-party script.
