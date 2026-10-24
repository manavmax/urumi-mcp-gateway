# POLISH_STORE - shopping-flow polish (branch polish-store)

Run rules honored: work only in this worktree/branch, no push, kind-urumi context
only, no helm upgrade/install, no wp-setup.yaml edits, docs/DECISIONS.md untouched.
Deployed via `make store-assets-image` (DOCKER_CONTEXT=colima) + `kubectl rollout
restart deployment/urumi-wordpress -n urumi`. `make demo-reset` was NOT needed.

## Commit trail (small commits)

1. `e076020` store: shopping-flow polish - nav fallback, search+submit, price
   filter, active chips, same-category related, sticky ATC, REST scheme fix,
   honest sort
2. `acd7333` store: polish verification harness + region pixel checks; fix stale
   gate product slug; recompress banner under 150KB cap
3. `377f9e2` store: category tiles ship 600px srcset derivatives (home 986KB ->
   748KB); wire page-weight checks into polish harness

## Decisions (and why)

- **Category nav = registered menu with a validated fallback.** The seeded
  "Primary" menu (wp-setup) still carries the old 4 categories
  (Apparel/Home/Accessories/Stationery) that no longer exist in the 29-product
  catalogue. The theme now renders the `primary` menu ONLY when every link
  resolves against the live shop/categories/products/pages; otherwise it builds
  the nav from the live `product_cat` terms in catalogue order (products.json).
  A stale menu can therefore never show a dead link. The empty legacy terms are
  also excluded from the shop pills (`count < 1` never renders).
- **Search suggestions** hit the same-origin Store API
  (`/wc/store/v1/products?search=`) with vanilla JS (`assets/store.js`): 200ms
  debounce, listbox semantics, arrow/Enter/Escape keys, "See all results"
  submits the existing GET form. No third-party requests.
- **REST scheme fix (theme-level).** The `urumi-internal-rest` mu-plugin marks
  every `/wp-json/` request as HTTPS (so in-cluster Basic auth works over
  plain HTTP). Side effect: Store API responses returned `https://` image URLs,
  which broke the mini-cart drawer thumbnails in the browser (the local ingress
  has no TLS). The theme now rewrites same-host `https://` URLs to `http://` in
  REST responses ONLY when the request itself arrived over plain HTTP
  (`X-Forwarded-Proto: http`, i.e. the local ingress path). Production (TLS)
  and in-cluster callers are untouched.
- **Honest sorting.** `woocommerce_catalog_orderby` drops `popularity` (seeded
  sales) and `rating` (no reviews exist); labels: Default sorting / Newest
  first / Price low-to-high / Price high-to-low.
- **Price filter** is a plain GET form using Woo core's `min_price`/`max_price`
  query vars (works with the product-collection block, no JS needed). A theme
  `pre_get_posts` guard (priority 9) drops empty price args so submitting one
  blank field cannot narrow the grid to nothing. The price range hint comes
  from products.json (single source of truth).
- **Active-filter chips** are server-rendered from the current query (category,
  price range, search term) with a "Clear all" chip; the block renders nothing
  when no filter is active.
- **Related products** replaced the Woo `related-products` pattern (category OR
  tag matches, 5 columns, centered titles) with a theme block that renders the
  shared tile grid from the product's own category, excluding the product.
- **Sticky add-to-cart (mobile)**: server-rendered bar (name, price, and either
  a one-tap GET add-to-cart form for simple products or a jump to the options
  form anchor for variable/out-of-stock), shown by `assets/store.js`
  IntersectionObserver only when the main form is out of view on <=767px.
- **Mini-cart drawer**: Woo block already renders items + subtotal; the footer
  was restyled so "Go to checkout" is the one clear solid button (full width)
  and "View my cart" is a quiet underlined text link.
- **Stylesheet dedupe**: assets/styles.css had ~700 lines of byte-identical
  duplicated rules (two concatenated copies). 71 earlier duplicate rules were
  removed keeping the LAST occurrence (cascade-safe); the one non-identical
  overlap (.urumi-404 max-width 560 vs 720 + input max-width) was consolidated
  to the effective values. Proven regression-free by a computed-style snapshot
  diff before/after (scripts/css-snapshot.mjs): the only diffs are the intended
  template changes (dynamic active pills, related block replacement).
- **Category tiles** now ship the sideloaded attachment's 600x750 derivative
  through srcset with an explicit `sizes` (tiles render ~430px wide). Home page
  weight dropped 986KB -> 748KB in the same measurement.
- **Page-weight gate**: the 800KB budget is measured on the real pages at 1440
  after the full-page capture (all lazy images loaded), same method as the
  previous STORE_VERIFY runs. Current: home 748KB, shop-with-filters 703KB,
  category 627KB, product 712KB, cart 573KB, checkout 540KB. The remaining bulk
  is WooCommerce's own mini-cart/block JS stack (~740KB), which the header
  mini-cart legitimately needs on every page; the theme cannot drop it without
  losing the drawer.
- **banner-desk-paper.webp recompressed** 183KB -> 134KB (q65) to honor the
  150KB image cap (the one file over cap; pre-existing from the photo pass).

## Per-item status (run rules GOAL 1-8)

1. **Header** - DONE. Logo; prominent search (260px input + attached Search
   button) with live suggestions (keyboard + ARIA); category nav (Shop +
   Collections dropdown with the 6 live categories + About + Shipping and
   returns) from the validated menu/live-taxonomy fallback; mobile menu overlay
   with search, categories and pages; mini-cart drawer with items, subtotal and
   one clear checkout button. Evidence: polish harness checks "header has
   category nav", "nav lists live categories", "nav omits dead categories",
   "search suggestions appear with results", "suggestion navigates to a
   product", "mini-cart shows item/Subtotal/checkout button", "mini-cart
   thumbnails load (scheme fix)", "mini-cart: one clear checkout button"
   (cart button transparent, checkout solid 498px).
2. **Shop and category pages** - DONE. Breadcrumbs on shop, category and search
   results; dynamic category pills with aria-current; price filter (GET form,
   $12-$79 hint); sort (default/newest/price asc/desc only); result count;
   active-filter chips with remove links + Clear all; quick add-to-cart on
   tiles (AJAX for simple, honest "Select options"/View for variable/OOS);
   honest stock flags ("Sold out" only when true - the current catalogue has no
   OOS products); category banner photos. Evidence: "shop breadcrumbs",
   "shop pills = All + 6 categories", "shop active chip shows price",
   "price filter applied to grid" (14 of 29 for $20-$40), "sort = default/
   newest/price asc/desc only", "quick add to cart on tiles" (14),
   "category chip shows current category", "category banner".
3. **Product page** - DONE. Gallery with desktop thumbnails / mobile swipe
   strip; price; honest stock line ("In stock - 31 ready to ship." /
   "Choose an option..." for variable); quantity input; mobile sticky
   add-to-cart (shows/hides with the form, verified at 390); Details +
   Shipping/COD accordions (only true statements: demo store, cash on
   delivery); related products from the same category excluding the product.
   Evidence: "PDP stock line", "PDP quantity", "390 sticky ATC shows/hides with
   the form", "PDP shipping/COD accordion", "related products present"
   (Dinner Plates/Ramen Bowl/Stoneware Mug for the Bud Vase page = ceramics).
4. **Cart and checkout** - DONE. Block cart with quantity steppers, remove
   links and a clear totals sidebar; block checkout stays one simple form with
   Cash on delivery and Place order. Evidence: "cart line items render",
   "cart totals", "cart qty steppers", "checkout loads block checkout",
   "COD option present", plus the e2e gate
   `CHECKOUT_PRODUCT=.../product/gel-pen-set/ node scripts/verify-checkout.mjs`:
   order #300 placed via block checkout (status processing), visible via the
   gateway woo__list_orders, test order deleted afterwards.
5. **Honesty** - DONE. No fake reviews, ratings, countdowns, "only N left" or
   invented discounts anywhere in the theme; the only sort options removed were
   precisely the dishonest ones (popularity/rating). A live sweep of home,
   shop, category, product and cart for review/rating/countdown/discount/
   social-proof patterns finds matches only inside Woo's internal JS config and
   REST preloads (average_rating:0 data fields), never in visible UI.
6. **No wp-setup edits** - DONE. helm/ untouched. Needs seeding (report only):
   the wp-setup "Primary" menu seed still inserts the four dead categories
   (Apparel/Home/Accessories/Stationery); the theme's validated fallback hides
   them, but the seed block should eventually list the six current categories.
   Also the empty legacy product_cat terms remain in the DB (harmless; theme
   filters them out).
7. **Gates** - ALL PASS on the local kind store (store.127.0.0.1.nip.io):
   - REST harness: `verify-store-v2.mjs rest --expect 29` - 10/10
     (count=29, images 29/29, gallery 29/29, sale present, OOS matches catalog,
     weight/dims/tags 29/29, 6 variable, 15 variations).
   - Contrast gate: `verify-store-contrast.mjs` - PASS on all sampled pages and
     rest/hover/focus states (product slug updated from the removed
     incense-holder to gel-pen-set).
   - e2e COD checkout: `verify-checkout.mjs` - PASS (see item 4).
   - Performance: zero third-party requests across all sampled pages; page
     weights under 800KB (numbers above); every shipped webp <= 150KB.
   - CSS dedupe regression check: computed-style snapshot diff - no
     unintentional diffs.
8. **Screenshots** - DONE (captured, machine-verified). artifacts/store/ holds
   the full set at 1440 and 390: home, shop-filters (with $20-$40 filter and
   chips), category (ceramics, banner), product, cart (with an item), checkout
   (with an item), minicart-open (drawer with item + subtotal + checkout),
   search-open (suggestion panel over the hero), plus mobile-menu-390.
   Programmatic verification: `verify-store-polish.mjs` - 66/66 checks (HTTP,
   broken images, third-party, console, overflow, DOM assertions, page weights)
   and `pixel-regions.py` - 7/7 region checks (drawer present right side with
   dark checkout button; suggestion panel band over the hero; sticky bar at the
   mobile bottom; shop filter band; photographic banner; cart totals).

## Needs human eyes (this session's model rejects image input)

The screenshots were verified structurally (DOM assertions, per-pixel region
statistics, color counts) but NOT visually - every previous attempt to read an
image in this environment failed with "this model does not support image
input". Please look at artifacts/store/*.png (16 files) for:

1. Search suggestions panel styling at 1440 and 390 (spacing, thumbnail crop).
2. The mini-cart drawer footer: one solid checkout button, quiet cart link,
   subtotal typography.
3. The price filter row on shop/category at both widths (wrapping at 390).
4. Active-filter chips look (surface-alt fill, hairline border, x mark).
5. The sticky add-to-cart bar on product-390 (name/price/button fit).
6. Related products row ("You may also like") under the PDP columns.
7. The recompressed banner-desk-paper.webp for visible quality loss (q65).
8. Anything the region checks cannot judge: photo crops, alt-text matches.

## Files touched

- store/theme/urumi-store/functions.php (blocks: category-nav pills/overlay/
  desktop, price-filter, active-filters, related, sticky-atc; REST scheme fix;
  honest orderby; price query guard; JS enqueue)
- store/theme/urumi-store/parts/header.html (dynamic nav + search submit)
- store/theme/urumi-store/templates/{archive-product,taxonomy-product_cat,
  product-search-results,search,single-product}.html
- store/theme/urumi-store/assets/styles.css (dedupe + new components)
- store/theme/urumi-store/assets/store.js (new: suggestions, sticky bar,
  filter guard, menu aria)
- store/images/banner-desk-paper.webp (recompressed under cap)
- scripts/{verify-store-polish.mjs,pixel-regions.py,css-snapshot.mjs} (new),
  scripts/{verify-store-contrast.mjs,verify-checkout.mjs} (playwright-core
  fallback + current product slug)
