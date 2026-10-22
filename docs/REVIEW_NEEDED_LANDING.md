# Landing page rebuild: items waiting for Manav (2026-10-22, ADR-086 pass)

Context: the `landing` branch was rebuilt to docs/LANDING_DESIGN.md (commit 1fb69a8) without
access to the cluster and without answers to the questions below. Everything was decided
unilaterally and logged as ADR-086; nothing blocks merging, but the items need your eyes.

## 1. Look at the screenshots — I could not (no image input this session)

**This pass was built by a model without image input.** Every visual check ran as scripted
probes (geometry, contrast, motion), but nobody has actually LOOKED at the page yet. Please open:

- `artifacts/landing/landing-desktop-dark.png`, `landing-desktop-light.png` (1440, full page)
- `artifacts/landing/landing-mobile-dark.png`, `landing-mobile-light.png` (390, full page)
- `artifacts/landing/frames/hero-frame-1..6.png` (6 frames of the hero graphic, 600ms apart;
  all six hashes differ, so the packet motion rendered)
- `artifacts/landing/review/` (32 per-section clips, both themes — easiest way to review
  section by section)

Things to judge by eye: hero prism composition and plane tilt, packet colours/density,
terminal look, marquee mask, sim cards, quote cards, the giant footer wordmark, light-theme
contrast feel. The scripted gates that DID pass: zero external requests, zero console errors,
no horizontal scroll at 375/768/1024/1440, 59/59 AA pairs both themes, sticky nav,
reduced-motion final values, simulation state machine, clipboard round-trips, budgets
(total 196KB/350KB, JS 31.9KB/40KB, fonts 78KB), 6 distinct hero frames.

## 2. Deviations from the spec to approve (details: docs/LANDING_DESIGN.md section 13, ADR-086)

- Dark `muted` darkened `#6C6E6A -> #8B8E89` (spec value fails WCAG AA below 24px: 3.9:1 on
  canvas, 3.3:1 on surface). Same role, AA-safe value.
- Light theme completed where the spec's front matter is silent: cards `#FFFFFF` on `#EEF2F0`
  bands, danger `#B3261E`, warn `#8A5A00`, plus an `on-deep` token (`#5EEAD4` dark /
  `#99F6E4` light) for text on accent-deep fills.
- Sim caption: spec said `scripts/regress-core.sh`, which does not exist in the repo; it now
  names `make test` and `scripts/verify-server-tools.mjs` (repo wins).
- The client-tabs config block is placed under the three steps (step 03); the 18-section
  anatomy has no other home for it.
- One extra small line in the closing band keeps the data-driven `storeProductCount` claim
  ("a 12-product catalog") after the redesign dropped the old features card it lived in.

## 3. Carried over from the first pass (still open)

1. **Apex DNS before enabling (prod)** — unchanged from ADR-083 notes.
2. **Confirm the repo URL** in `features.js` (`https://github.com/urumi-ai/mcp-gateway`).
3. **Flip beyond-the-brief items only after their branches merge**; then `make landing-image`.
4. **Demo video** stays hidden until `landing.videoUrl` is set.
5. **www subdomain** still not served; one more Ingress rule if wanted.
6. **Image tag**: built locally as `urumi/landing:0.2.0`; for GHCR use `make images-push` and
   pin the tag in values-prod (values-local pins `0.1.0` — bump it when you enable on kind).
7. **Live check on kind** (`make landing-image && make helm-local`, then the apex host); the
   in-cluster path was chart-reviewed and helm-templated only, never live-run from this session.

## Evidence summary (this pass)

- `docker build -t urumi/landing:0.2.0 src/landing`; container run as uid 101 on 127.0.0.1:8090;
  `/`, styles, scripts, fonts all 200; CSP self-only + nosniff + no-referrer + DENY on responses
  (unchanged from ADR-080); `font/woff2` served with 7-day cache.
- `node scripts/landing-verify.mjs` (against the container): LANDING VERIFY PASSED — 7 sweeps
  OK, zero external requests, zero console errors, contrast 59/59 in both themes, budgets
  total=196,030B (limit 358,400B) js=31,908B (limit 40,960B) fonts=78,064B, 6 hero frames
  saved, reduced-motion gates green, simulation/clipboard gates green.
- Scripted probes: packets move (both accent and violet seen in flight), hub pulse animating,
  marquee translating, audit rows streaming, terminal looping, steps track drawing,
  diagram replay 12 -> 1 -> 12, spotlight `--mx/--my` set on pointermove, toast on chip copy,
  announcement dismissal persisted across reload, mobile menu sheet opens.
- `helm lint ./helm` with values-local: 0 failed. `helm template` flag-off: zero landing lines;
  with values-local: Deployment/Service/Ingress/NetworkPolicy/SA render.
- Page weight: 196KB raw total (HTML 48KB, CSS 38KB, JS 31.9KB, fonts 78KB, favicon+rest);
  far under the 350KB budget; gzip will land well under half of that.
