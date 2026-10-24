# Landing page: fix pass items for Manav (2026-10-22 late, ADR-087)

Context: the nav fix pass (user-reported bugs + nav modernisation + hero graphic fixes) ran
without image input — this session's model cannot view images, so every visual claim below is
backed by scripted gates and pixel probes, not eyes. ADR-087 records the root causes and fixes.

## 1. Still the top item: look at the new screenshots

Files, all regenerated after the fix pass:

- `artifacts/landing/landing-{desktop,mobile}-{dark,light}.png` (1440 / 390 full pages)
- `artifacts/landing/frames/hero-frame-1..6.png` (now with packets actually painting:
  78-179 teal pixels per frame, violet return packets in three frames)
- `artifacts/landing/review/` (32 per-section clips, both themes, plus
  `sheet-open-{dark,light}.png` showing the new mobile overlay open)

Judge by eye: the new nav (logomark, centre pill group, sliding highlight, 64->56 shrink),
the overlay sheet (spacing, large links, buttons at the bottom), the hero's dashed lines and
packet glow, the smaller fainter planes, and the 46-percent-visible graphic at 1440x900.

## 2. What was reported and fixed (verified root causes, ADR-087)

- Mobile menu rendered open on desktop from load: author `display` rules beat the UA
  `[hidden]` rule. Fixed globally with `[hidden] { display: none !important }` plus a
  desktop media guard; the sheet is now a below-900px full-screen overlay.
- "View on GitHub" nearly invisible in both themes: `.nav-sheet a { color: var(--body) }`
  clobbered the pill colors inside the always-open sheet (1.75:1 dark). Scoped to
  `.sheet-links a`; the open sheet now passes contrast 3/3 in both themes.
- Found during the pass: the hero packets had never painted (CSS `opacity: 0` overrode the
  per-frame opacity attribute). Fixed; a regression gate now asserts packets paint.
- `#simIssue` ("Issue new key") was also visible-while-hidden from the same cascade bug; fixed
  by the global guard.

## 3. Carried over from earlier passes (still open)

1. Apex DNS before enabling prod. 2. DONE (ADR-088): every GitHub link now builds from the
   one chart value `landing.repoUrl`, defaulted to https://github.com/manavmax/urumi-mcp-gateway —
   confirm that is the repo you want public; docs links resolve to /blob/main/<path> and all
   five paths were proven to exist on main. 3. Flip beyond-the-brief items only after merge;
4. demo video stays hidden until `landing.videoUrl`; 5. www subdomain not served; 6. DONE in the
   cleanup batch: values-local and `make landing-image` now both pin `urumi/landing:0.2.0`
   (the previously ad-hoc verify tag), so `make helm-local` rolls the landing pod onto the
   new build; 7. live kind run when free.

## Evidence summary (this pass)

- `node scripts/landing-verify.mjs` (dockerised page, uid 101, port 8090):
  LANDING VERIFY PASSED — 7 sweep cases OK, nav-375 routes OK in both themes, nav-spy OK,
  reduced-motion OK, hero decor gates OK. Contrast 63/63 per theme. Budgets: total
  204,633B / 350KB, JS 36,471B / 40KB, fonts 78,064B.
- Pixel probes (no image input): frame packet-pixel counts above; nav pill luminance spread
  221 (dark) / 230 (light) proving pill text paints.
- `helm lint`: 0 failures; flag-off `helm template`: zero landing lines; values-local
  renders the landing resources. No Helm files changed; nothing pushed.
