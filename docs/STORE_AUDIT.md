# Storefront audit (store-v2 branch, before redesign)

Date: 2026-10-22. Baseline: `main` as of commit `8cf8f73` (ADR-052/053), branch `store-v2`.

## Method

- Throwaway docker compose stack (`artifacts/store-compose/`, gitignored) running the EXACT
  hardened images the cluster runs for this commit (`ghcr.io/manavmax/wordpress:1.0.2-8cf8f73`,
  `ghcr.io/manavmax/wp-cli:1.0.2-8cf8f73`, `mariadb:11.4`, store-assets built from `store/`),
  with wp-setup executed as the REAL script rendered from `helm/templates/jobs/wp-setup.yaml`
  (12 products, current theme). No kind cluster, no kubectl, no helm install was touched.
- Playwright (playwright-core from the dashboard devDependencies) at 1440x900 and 390x844,
  reduced motion: every page (home, shop, category, product, cart, checkout, search, 404,
  my-account) screenshotted to `artifacts/store-audit/` (gitignored) with checks for HTTP,
  broken images, third-party requests, console errors, horizontal overflow, mobile menu.
- WCAG contrast gate `scripts/verify-store-contrast.mjs` across pages in rest/hover/focus states.
- DOM/geometry analysis (`artifacts/store-audit/dom-audit.mjs`): h1s, image dimensions (CLS),
  accessible names, tap targets, font sizes, sticky-nav overlap, focus rules, reduced motion,
  form labels, checkout validation messages.
- End-to-end COD checkout in a real browser + order confirmed via the Woo REST API.

**Honest limitation:** the screenshots exist, but the assistant in this session cannot view
images (model limitation). The audit is therefore DOM/measurement-based; every finding below
comes from computed styles, geometry and network/console evidence, not eyeballing. A human
visual pass over `artifacts/store-audit/` is still worthwhile; it is listed in
docs/REVIEW_NEEDED_STORE.md.

## Results that already pass (kept as gates)

- WCAG contrast: PASS on every sampled page and state (rest, hover, focus-visible).
  The theme's token family (ink `#14171C`, page `#ECEBE7`, white cards, muted `#5F6673`,
  ring `rgba(185,196,221,.55)`) is kept by the redesign; refined, not replaced.
- Zero third-party requests on every page (offline requirement already met; emoji,
  gravatars, oEmbed, resource hints removed at theme level).
- Both fonts self-hosted (Instrument Serif + Inter woff2 in the theme), font-display: swap.
- :focus-visible rule present and applied; checkout validation messages render inline
  ("Please enter a valid email address", ...) with COD preselected.
- Reduced motion collapses animations (hero float measured at 1e-05s under
  `prefers-reduced-motion: reduce`).
- No horizontal overflow at 1440 or 390 on any audited page; sticky nav never covers content.
- Mobile menu overlay opens/closes at 390.
- e2e COD checkout places a real order (order #44, status processing, payment_method=cod,
  visible via `/wp-json/wc/v3/orders`).
- wp-setup (12 products) wall time: 92 s under arm64-emulated amd64 (pessimistic vs the
  native amd64 cluster).

## Findings to fix (the redesign backlog)

1. **Brand and niche are incoherent.** "Urumi Store" sells a tee, hoodie and sneakers next
   to candles and notebooks: a branded merch table, not a store. Decision: a fictional brand
   and one coherent niche (see docs/DECISIONS.md ADR-070).
2. **Catalog depth and completeness.** 12 products; no sale prices, no stock quantities, no
   out-of-stock items, no weight/dimensions, no tags, no gallery images, no variable
   products. The brief's full product model needs the seed step extended (ADR-071).
3. **No sale / sold-out badges.** The tile and PDP render only the "New" tag; on-sale and
   out-of-stock states are invisible in the grid and on the product page.
4. **Header search is a dead icon.** It links to `/?s=` (empty query); there is no way to
   type a search from the header. Fix: a real GET form (works without JS, no CSP concerns).
5. **404 page is a dead end.** No search form, no link to the shop; only "Back home".
6. **"New" badge is 11px.** The only sub-12px text on the site (8 nodes on home). Bump to 12px.
7. **Block-cart quantity selector is unstyled** (default WooCommerce look, off-brand next to
   the restyled inputs).
8. **No newsletter-style block.** The brief asks for one that collects no data.
9. **Hardcoded content ties the theme to the old catalog:** header/footer nav category links,
   hero cutout SKU (`URUMI-HOODIE-001`), split-panel SKU (`URUMI-THROW-001`), hero preload.
   These break silently with a new catalog; the hero/split must be picked from products.json.
10. **Six categories need six tints** (the tint map and CSS hardcode four).
11. **my-account is plain.** Login form labels are correct (checked); the page needs the same
    card/pill treatment as the rest.
12. **Checkout/cart empty state** shows identical content (core WooCommerce behavior); noted,
    not a bug. With 32+ products and a filled cart the pages carry the redesign.
13. **Single-match search redirects to the product** (core WooCommerce 302). Not a bug; the
    redesigned search template is verified with a multi-match query.
14. **Image preloads and hero art** reference files that will not exist after the rebrand
    (would 404 silently into generic alt text); handled by the theme rework.

## Artifacts

- Screenshots (1440 + 390, all pages + mobile menu): `artifacts/store-audit/` (gitignored).
- DOM audit script: `artifacts/store-audit/dom-audit.mjs` (gitignored).
- Harness: `artifacts/store-compose/` (gitignored): compose.yml, rendered/wp-setup.sh,
  up.sh, run-wpsetup.sh, wpcli.sh, .env (600, contains only local secrets).
