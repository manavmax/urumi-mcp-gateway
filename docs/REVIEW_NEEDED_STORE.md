# Review needed (store v2 photo-first pass) - for Manav

## READ THIS FIRST: I could not view images this session

The model running this pass cannot view images (the read tool rejects image
input for it). Per your instruction ("if you cannot, build everything except
the photo selection, say so at the top of your report, and stop. Do not pick
photos blindly"), I:

- did NOT choose any photograph,
- did NOT rebuild product names/descriptions from photos,
- did NOT eyeball any screenshot or candidate sheet.

Everything else is built, committed in small steps on `store-v2`, and
verified with real runs (details below and in docs/STORE_VERIFY.md). The
photo step is prepared end to end and should take a photo-capable session (or
you) under an hour.

## 1. What is ready for photo curation

- `artifacts/store-photos/cache/search-*.json`: 10 cached Unsplash searches
  (ceramics x3, textiles x2, candles, desk, kitchen board, carry, lifestyle),
  30 portrait, high-content-filter results each. Cached = no API budget spent
  on re-runs (50 req/h demo limit).
- `artifacts/store-photos/sheets/sheet-*.jpg`: candidate sheets, 24 per query
  with index numbers ([NN]) and descriptions.
- `scripts/fetch-unsplash.py`: reads `.unsplash_key` only inside the script
  (never printed; the file is gitignored in .gitignore AND .git/info/exclude).
- Curation workflow: pick per category from the sheets, write
  `artifacts/store-photos/choices.json` (format documented at the top of
  `scripts/process-photos.py`), then run
  `python3 scripts/process-photos.py` (needs Pillow; a venv with it lives at
  /var/folders/wp/mfjhmzgj5vx35659rm6y4v2m0000gn/T/kilo/venv-img or pip install pillow).
  It downloads at w=1600 with the download_location ping, crops 4:5 at
  1200px, encodes webp q80 <=150KB, writes the gallery detail crops, the
  manifest (artifacts + committed store/photos-manifest.json),
  docs/IMAGE_CREDITS.md rows and the contact sheet at
  artifacts/store-photos/contact-sheet.png.
- After curation: rebuild products.json FROM the photos (names for what the
  photo shows, 24-32 products, 4 variable), run
  `python3 scripts/regen-demo-seeds.py`, then the seed picks the .webp files
  up automatically (defaults to <SKU>.webp).

## 2. Interim state you will see at http://localhost:18088 (compose stack left running)

- 36 products (old v2 names/copy, one invented origin claim removed), no
  photographs: neutral beige tile frames, dark warm hero ground with the
  white headline, all-AA verified.
- Theme fully rebuilt to docs/STORE_DESIGN.md: warm neutrals, Newsreader
  Variable + Hanken Grotesk Variable (self-hosted, OFL, docs/FONT_CREDITS.md),
  sharp corners, no shadows, no accent colour, hairlines, outline/solid/text
  buttons, 44px inputs, vertical PDP thumbs, mobile full-screen menu overlay,
  reduced-motion support, 4/3/2 responsive grids, sticky header with
  Collections dropdown.
- Footer: four columns, "A demo store. No real orders are shipped.",
  "Photography from Unsplash." -> /image-credits/ (200, licence copy; fills
  from store/photos-manifest.json after curation).

## 3. Real-run verification results (docs/STORE_VERIFY.md has the table)

- Fresh wp-setup 54 s; second run idempotent: created=0 kept=36, 45 s.
- e2e COD checkout green through the block checkout; order visible via REST
  with payment_method=cod.
- 91/93 harness checks pass. The 2 fails are the known cosmetic Woo
  ResizeObserver console warnings (block cart/checkout), unchanged from the
  previous pass.
- WCAG gate passes every rest/hover/focus sample after fixes (ADR-080 logs
  the two token deviations: neutral-4 for struck prices and sold-out flags;
  dark hero ground before photos).
- Zero third-party requests on every page; no horizontal overflow; home
  470 KB (gate: 800 KB) without photos; demo-reset dry-run: 36 KEEP,
  0 product deletions.
- 19 screenshots at 1440 + 390 in artifacts/store-v2-shots (gitignored) -
  UNREVIEWED BY EYE by me; a human pass over them would confirm the "looks"
  side.

## 4. Watch-outs after photos land

- Re-measure home weight with tiles fetching real variants; if it drifts
  over 800 KB, tighten the WP image quality filter (functions.php) or encode
  the 600px variants harder (pipeline ceiling is a one-line change).
- Re-run the contrast gate: the hero headline will sit on a real photograph
  plus the 20 percent veil; verify AA on the chosen hero (spec requires it).
- The harness rotates the Woo key on every wp-setup run (no K8s Secret in
  compose); in-cluster the woo-secrets Secret prevents this - unchanged.

## 5. Files touched outside the store layer (flagged per your instruction)

- helm/templates/jobs/wp-setup.yaml (the ONE file, ADR-071 pattern): image
  fallback .png -> .webp; new Photography credits page. Idempotency verified.
- helm/templates/deployment-wordpress.yaml: one added `cp` line in the
  store-assets initContainer (photos-manifest.json), same ADR-038 semantics.
- No src/gateway, src/dashboard, src/woo-mcp change. Nothing pushed, nothing
  merged, main untouched, no cluster/kubectl/helm-release touched (only
  read-only `helm template` for the harness render).

## 6. Suggested image tag for the store-assets image (current, photo-less)

`urumi/store-assets:3.0.0-<sha of this branch head>` (built from store/ with
the usual make target; ships theme + fonts + products.json + photos-manifest).
After curation, rebuild as `urumi/store-assets:3.1.0-<sha>` (photos included)
- do not reuse the 3.0.0 tag for a different content set.

## 7. Honest remaining weaknesses

- Product copy still describes the v2 objects; it will be rewritten FROM the
  chosen photos (that step is inherently photo-dependent).
- The 36-product interim catalogue means categories carry uneven tile counts
  after the rebuild to 24-32; re-run regen-demo-seeds.py then.
- The contact sheet script exists but has no real photos to compose yet.
- Two cosmetic Woo console warnings remain (item 3 above); not fixable
  without patching Woo block internals.
