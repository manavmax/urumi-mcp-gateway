# POLISH_LANDING — hero order + alternate-band illustrations (branch `polish-landing`)

Date: 2026-10-24. Worktree: `Urumi_AI-polish-landing`. Verified against the dockerised page
(`urumi/landing:polish-test`, local container on 127.0.0.1:8090, built with `docker --context colima`,
no cluster interaction, no helm runs). Gates: `LANDING_URL=http://127.0.0.1:8090 node scripts/landing-verify.mjs`.

## Reviewer limitation (read first)

This session's model **cannot view images** (the `read` tool rejects image input; re-tested at the start
of this run and again mid-run). Everything below is therefore verified with the real gates plus
programmatic pixel analysis of the screenshots (empty-run detection, painted-content fractions,
stroke-colour presence) — not with eyes. A human should still eyeball the screenshots in
`artifacts/landing/` for aesthetics; the specific spots are listed under "Needs human eyes".

## 1. HERO ORDER — DONE

Owner-decided order implemented in `src/landing/index.html`: heading → subtext → flow graphic
(clients → /mcp → servers) → sample chat card → two buttons. `hero-note` stays last; nothing else in
the hero changed (copy, animations, packet behaviour, aria-label all untouched — `main.js` byte-identical).

Evidence:
- DOM order at 1440 and 390: `display, lead, hero-visual, terminal, hero-actions, hero-note`.
- Desktop: graphic top=352, h=560 → **97.8% visible at load** (gate ≥45%).
- Mobile 390: graphic **66.7% visible**, heading+lead fully in the first viewport; order asserted by the gate.
- The verify gate was re-expressed for the new order: the old mobile assertion ("terminal top and
  actions bottom within 844px") encoded the previous graphic-last order and is arithmetically
  incompatible with the owner's order on a 390×844 screen. It now asserts: heading/subtext in the
  first viewport, ≥45% of the graphic visible (mirrors desktop ADR-087), and the exact sequence
  h1 → lead → graphic → terminal → actions with no overlap.
- CSS consequences: removed the now-meaningless `.hv-fade` strip (it blended the graphic's bottom into
  the section below; the graphic is mid-hero now) and the `.hero-visual + * { margin-top: 0 }` rule;
  hero gained `padding-bottom: var(--s-xxl)`.

### Nav CTA on mobile — DONE

"Open dashboard" stays in the top bar at every width (below 900px it was hidden and only reachable via
the sheet). At ≤899px: grid `1fr auto`, GitHub button hidden, dashboard CTA kept; ≤479px tightens
paddings/font so wordmark + CTA + theme toggle + menu button fit 375px (measured: wordmark right 143,
CTA 158–279, toggles to 359 = viewport−16 at 375; no overflow, `scrollWidth == viewport` at 320/375/390);
≤359px the wordmark is icon-only.

## 2. ILLUSTRATIONS — DONE (for every visible alternate band; `#beyond` ships one too)

The alternate `band-alt` sections are: **#features, #tour, #control, #kubernetes, #notes**, plus
**#beyond** (hidden until a feature is enabled in `features.js` — it got an illustration as well so it
is never plain if switched on).

Design (v2, after reviewer feedback that the first pass read as unexplained slivers): each section
head and its illustration now share a `band-head` row — head text left, a compact **labeled**
schematic right (`.band-art`, 360×120 viewBox rendered at min(380px, 100%), ~1:1 scale at every
breakpoint, stacking under the head below 900px; #control's ledger sits inside its text column since
that section has no head block). Every part is named with 10px mono labels using the same token fills
as the hero diagram text (all AA against the band background in both themes):

- `#features` — clients → "one URL" → gateway (keyhole, accented) → "tools" → MCP servers.
- `#tour` — a trace with checkpoints labeled client / checks / audit, an outbound teal pulse, a violet
  return pulse with "result returns"; the full six-step diagram follows below in the section proper.
- `#control` — the audit ledger: time/tool/user/took dashes per row, ok-circle and warn-triangle
  outcomes, a blinking accent write-caret on the newest row.
- `#kubernetes` — public (through-arrows) / private (padlock) / state (volume cylinder) boxes on one
  wire, each labeled, with three pulsing pod squares above the private tier.
- `#notes` — two leaning quote bars, three passage lines (the pulled claim accented) and the
  chain-link to the source.
- `#beyond` — the queue: three switched-off toggles on a track, the next item's knob accented
  ("next up").

Rules followed: token-driven throughout (`--flow-line`, `--ba-box`, `--hairline-strong`, `--accent`,
`--violet`, `--warn`, `--faint`, `--muted`) so both themes work; `aria-hidden` wrappers (the labels
are for sighted readers; the section head text explains the section to AT); motion is calm, CSS-only,
directional (dash drift, a pulse per direction, pod pulse, caret blink) and fully disabled under
`prefers-reduced-motion` (the two pure-motion pulse paths are `visibility: hidden` there). No copy,
existing animation, or interactive behaviour changed; zero JS added (`js=37,413B` unchanged from
baseline).

Evidence: `artifacts/landing/qa/art-*.png` + canvas histograms — raised boxes 22-24% of clip area over
68-71% band background, label pixels present in dark and light at both widths; SVG geometry
hand-checked to fit its viewBox.

## 3. BUDGETS AND GATES — DONE

- Budgets (from real response bodies): **total 216,073B ≤ 358,400B**, **JS 37,413B ≤ 40,960B**
  (baseline was 205,019B / 37,413B — the +11KB is the six SVG strips + band-art CSS).
- All gates pass (three consecutive full runs, all `OK`): zero external requests, zero console errors,
  no horizontal scroll at 375/768/1024/1440 (and 320 manually), **contrast 63/63 in both themes**,
  sticky nav + announcement dismiss, mobile nav sheet (routes/trap/lock/contrast), scroll-spy,
  outbound links (16 GitHub, all repo-canonical, 5 blob paths exist on main), break-it-yourself
  simulation, copy buttons, hero frames + packet visibility, hero decor opacities, reduced-motion.

## 4. SCREENSHOTS — DONE (generated + pixel-audited; human eyeball still recommended)

Inventory in gitignored `artifacts/landing/`:
- `full/landing-{desktop,mobile}-{dark,light}-full.png` — full page at 1440 and 390, dark and light.
- `clips/{desktop,mobile}-{dark,light}/NN-<section>.png` — one clip per section (15 visible:
  top, built-with, features, how, tour, sim-section, control, fleet, kubernetes, security, notes,
  docs, closing, footer), each size × theme.
- `qa/art-*.png` — band-art strips; `qa/pixel-report.json` — audit results.
- Plus the verify script's own `landing-*.png` and `frames/hero-frame-1..6.png`.

Method: `scripts/landing-shots.mjs` (playwright-core, the existing devDep) captures everything, then
feeds every PNG back through a canvas to measure painted content. **80 images, zero empty vertical
runs ≥450px** in both themes at both widths; every band-art clip shows painted strokes.

### Two harness defects found and fixed (pre-existing, exposed by the audit)

1. **Blank lower sections in every full-page capture** (baseline artifacts had identical blank runs):
   `html { scroll-behavior: smooth }` made the verify script's `scrollTo(0, y)` reveal sweep animate,
   so the real scroll position never reached the lower page before the jump back to top; the
   IntersectionObserver reveals stayed at `io-pre` (opacity 0) below ~2400px. The sweep now uses
   `behavior: "instant"` jumps. Gates unaffected; the screenshots this gate is supposed to produce are
   now actually usable for review.
2. **Flaky scroll-lock gate** (`scrollY=1` race): the lock (`html.nav-open { overflow: hidden }`) stops
   user scrolling but not programmatic `scrollTo`, so the old immediate read raced the smooth-scroll's
   first frame. Now driven with a real `page.mouse.wheel` gesture and a settle wait — deterministic
   and closer to the behaviour the page promises.

## Follow-up: "black graphics" report (2026-10-24, after review)

Cause: nginx served `styles.css` (and js/svg/woff2) with `expires 7d; Cache-Control: public` at
unversioned URLs while `index.html` is not long-cached. A browser that had visited earlier in the day
kept the pre-band-art stylesheet for 7 days and rendered the new SVGs with default styling — solid
black shapes, no strokes, no motion. Fixes:

- nginx: the static-asset location now sends `Cache-Control: no-cache` (revalidate via ETag; one 304
  per asset per load) instead of a 7-day public cache. The site has no build step, so asset URLs are
  never content-hashed and long caches guarantee stale-HTML/CSS mismatches after every redesign.
- One-time cache-bust: the stylesheet link is now `/styles.css?v=2`, so browsers already holding the
  old 7-day copy fetch the new CSS on the next normal reload.
- Dark-mode legibility of the strips themselves: box fills were `--surface` (#1A1C19) on the
  `--surface-alt` band (#131412) — near-invisible dark-on-dark. New `--ba-box` token
  (#2C2E2B dark / #FFFFFF light) used by `.ba-box/.ba-gate/.ba-check`. Verified by canvas histogram of
  the dark strip: band 19,20,18 = 80.5%, raised boxes 44,46,43 = 14.8%, teal accents present.

All gates re-pass (total 216,414B ≤ 358,400B, JS unchanged, contrast 63/63 both themes). Motion note:
the strips are calm by design — dash drift, pod pulse, caret blink, tour pulses; with
`prefers-reduced-motion: reduce` the pulses are hidden and the rest is static.

## Needs human eyes

- Aesthetics of the six strips (balance, whether the compositions read well at 342px on mobile).
- That the calm motion feels right at real speed (the pixel audit can only prove presence, not taste).
- The mobile hero: with the owner's order, the chat card and buttons are below the 844px fold —
  confirm that reads well (the order itself is gated).
- Full pages in `full/` end to end for anything a pixel metric can't judge.

## Commits

- `aab9bf8` hero order per owner decision (+ mobile nav CTA, verify gate re-expression, sim-log wrap fix)
- `54ed4ca` band-art illustrations for all six alternate bands
- `7f768cb` screenshot-harness fixes (reveal sweep, scroll-lock gate) + shots/audit tooling
