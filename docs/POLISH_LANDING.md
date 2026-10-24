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
is never plain if switched on). Each opens with an original inline SVG strip (`.band-art`, 640×120
viewBox, scales to 342×65 on mobile), drawn for this product, no text glyphs, no external files:

- `#features` — three client lanes converging through one accent-gated hexagon out to two servers
  (connect · control · run).
- `#tour` — a dashed trace with six checkpoint circles (the gateway check is an accent diamond), an
  outbound teal pulse, a violet return pulse, and audit ticks below ("checked and written down").
- `#control` — three ledger rows with time/tool/user/duration dashes, ok-circle and warn-triangle
  outcome glyphs, and a blinking accent write-caret on the newest row.
- `#kubernetes` — public (through-arrows), private (padlock) and state (volume cylinder) tiers sitting
  on one wire, three live pod squares pulsing above the private tier.
- `#notes` — two leaning quote bars, three passage lines (the pulled claim accented), a chain-link to
  the source, a citation under-line.
- `#beyond` — the queue: three switched-off toggles on a track, the next item's knob accented.

Rules followed: token-driven (`--flow-line`, `--hairline-strong`, `--surface`, `--accent`, `--violet`,
`--warn`, `--faint`) so both themes work; `aria-hidden` wrappers; motion is calm, CSS-only, and
directional (dash drift, a pulse per direction, pod pulse, caret blink) — and fully disabled under
`prefers-reduced-motion` (the global rule stops them; the two pure-motion pulse paths are additionally
`visibility: hidden` there). No copy, existing animation, or interactive behaviour changed; zero JS
added (`js=37,413B` unchanged from baseline).

Evidence: `artifacts/landing/qa/art-*.png` + `scripts/landing-artcolors.mjs` output — accent/violet/warn
strokes present in all four size×theme variants of every strip (e.g. notes strip 2.9% teal pixels,
kubernetes 0.5–0.75%, control warn glyph present); SVG geometry hand-checked to fit its viewBox.

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
