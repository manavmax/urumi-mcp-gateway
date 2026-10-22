# Review needed (store v2) - for Manav

Branch `store-v2`, worktree `Urumi_AI-store`. Decisions logged as ADR-070..075
in docs/DECISIONS.md. Nothing pushed, nothing merged, main untouched.

## 1. One file outside the store layer was edited (flagged per your instruction)

`helm/templates/jobs/wp-setup.yaml` - the seed PHP lives inline there and
there is no hook for it. Supporting the full product model (sale price,
manage-stock/out-of-stock, weight/dimensions, tags, gallery sideloads, variable
products with per-variation SKU/price/stock) required extending that seed. All
wp-setup changes are in that ONE file: seed extension (idempotent semantics
unchanged), About/Shipping page copy for the new brand, blogname +
blogdescription, and the Primary menu items (now the six new categories). No
other helm file, no src/gateway, src/dashboard or src/woo-mcp change. Please
review the diff of that file carefully; the verification ran the exact
rendered script from it (ADR-075).

## 2. The audit is DOM-based, not eyeballed

I cannot view images in this environment (model limitation), so
docs/STORE_AUDIT.md findings come from computed styles, geometry, network and
console evidence; the contrast gate and 93 screenshot checks pass. The
screenshots are saved (both before and after) - a quick human pass over
`artifacts/store-final/` would confirm the "looks" side. Worth a look:
home hero balance, product-art style consistency, checkout spacing.

## 3. Brand and catalog: your call to keep

Invented brand **Loam & Ember** (fictional, no real store copied), niche
"slow-made home and desk goods", six categories, 36 products. The old
URUMI-* products are NOT deleted by the seed (idempotent by design) - they
fall out of a live catalog via `make demo-reset` (its keep-manifest is now the
36 LOAM-* SKUs) or vanish on any fresh install. If you'd rather keep Urumi as
the store brand, the rename points are: products.json brand field, theme
header/footer wordmarks, functions.php brand constant, and the wp-setup page
copy (same one file).

## 4. wp-setup details worth knowing

- Every wp-setup run in an environment WITHOUT the woo-secrets Secret rotates
  the Woo API key (deletes existing keys). In-cluster the Secret prevents
  this; in the compose harness the harness re-creates its verify key after
  each run.
- `show_avatars` logs "Error: Could not update option" on re-runs after the
  theme is active - the theme forces avatars off via a filter, so the option
  update is a no-op. Benign; the effective setting is what we want.
- Force mode (`STORE_SEED_FORCE=1`) re-attaches main images, leaving the old
  attachments as orphans for `make demo-reset` media cleanup (by design).

## 5. Remaining imperfections (honest list)

- Product art is flat illustration in the established style; it is consistent
  but simple - a human eye should confirm it reads as "premium-minimal" at
  1440 (the generator is parametric; art tweaks are cheap).
- The newsletter block is honest-by-design (GET to the same page + note), but
  if you want it to look fully functional without the note, say so and I'll
  wire it to a fake success state instead.
- Single-match product search 302-redirects to the product (core WooCommerce).
  The search template renders properly for multi-match queries.
- Checkout is the WooCommerce block checkout with theme styling; its
  "ResizeObserver loop" console warning is a known Woo SPA artifact (cosmetic).
- Order-received is verified at 1440 and 390 via the real checkout flow, but I
  have not restyled Woo's order-details table exhaustively (it uses the
  order-confirmation block with theme tokens).

## 6. Suggested image tag for the store-assets image

`urumi/store-assets:2.0.0-<sha of this branch head>` (built from store/ with
`make store-assets-image`; 155 PNG files, 1.9 MB total). The theme version
constant is bumped to 2.0.1 for cache busting.

## 7. Compose harness (throwaway, gitignored)

`artifacts/store-compose/` holds the harness (compose.yml, rendered
wp-setup.sh, scripts, .env with local-only secrets chmod 600). It is not part
of the repo. Left running on port 18088 for you to poke at:
`docker compose -f artifacts/store-compose/compose.yml -p store-v2-verify ps`.
Tear down with `down -v` when done.
