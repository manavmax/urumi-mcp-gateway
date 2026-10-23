# Store photo pass - applied, ready for your eyeball review

The reviewer's selections (index numbers on `artifacts/store-photos/sheets/`)
have been applied end to end on `store-v2`: curation file, pipeline run,
catalogue cut, banner support, local kind deploy. **The session that applied
them could not view images** (the read tool rejects image input for this
model), so the mechanical work is done and verified, but three things below
genuinely need your eyes.

## 1. What was applied (no photo choices made by the machine)

- `artifacts/store-photos/choices.json` (gitignored) records the selection
  verbatim: your index numbers per sheet, hero = lifestyle 08, banners per
  category, and the product assignment (flagship gets the first photo of its
  list; banner photos never used as product photos; 38 unique Unsplash photo
  ids, zero duplicates, zero banner/product overlap).
- `scripts/process-photos.py` ran for real: 37 photos downloaded at w=1600
  with the Unsplash `download_location` ping (cached flags make re-runs
  ping-free), 4:5 grid crops at 960x1200, webp q80->q60 under 150 KB per
  product file, hero.webp wide crop, 6 banner-<slug>.webp wide crops,
  editorial.webp, `store/photos-manifest.json`, `docs/IMAGE_CREDITS.md`, and
  TWO review sheets (item 2).
- The catalogue is cut from 36 to 29 products (target 28-32; candles capped at
  4): ceramics 4, textiles 6, candles-care 4, desk-paper 3, kitchen 6, carry 6.
  The 7 removed products and the reasons are in docs/DECISIONS.md (ADR-082) -
  exactly: LOAM-CER-005, LOAM-CER-006, LOAM-CND-004, LOAM-CND-006,
  LOAM-DSK-003, LOAM-DSK-004, LOAM-DSK-006.
- `scripts/demo-seeds.json` regenerated (29 parent SKUs): the next
  `make demo-reset` deletes the removed products from the live store; a fresh
  seed never creates them.
- Category banners: new `urumi-store/category-banner` theme block renders
  `banner-<slug>.webp` at the top of each category archive (ADR-083); no seed
  change - banners are files like the hero.
- Deployed to the LOCAL kind cluster (context kind-urumi only): store-assets
  image rebuilt, WordPress rolled, wp-setup re-attached images, demo reset
  removed the 7 SKUs. Nothing pushed; main untouched.

## 2. REVIEW WITH YOUR EYES (the machine could not see)

1. **Desk crops**: every desk product photo and the desk banner carry a
   centre zoom crop (1.3x main, tighter for the banner) intended to satisfy
   "crop to notebook/pen only; crop out laptops, earbuds, phones" - applied
   blind. Check `artifacts/store-photos/contact-sheet-products.png`
   (LOAM-DSK-001/002/005) and `contact-sheet-hero-banners.png` (desk banner).
   If a crop still shows tech, adjust the "zoom" value in choices.json and
   re-run the pipeline (cached downloads make this cheap).
2. **Hero AA contrast**: the headline now sits on the lifestyle-08 photograph
   behind the 20 percent veil. Run the contrast gate
   (`node scripts/verify-store-contrast.mjs` against the store URL); if it
   fails, switch the hero to the designated backup (lifestyle 02) by editing
   choices.json's "hero" and re-running.
3. **Photo/product matches the alt text flagged**: Unsplash alt text is often
   wrong, and the reviewer selected from the sheets, not the alt text - but
   three pairings looked odd on paper and are worth a glance on the products
   sheet: KIT-001 Serving Board (kitchen 00), CAR-005/006 (carry 20/18), and
   DSK-001 Notebook (desk 11). Swap only if the photo truly shows the wrong
   object; swap within the same category pool to keep one-photo-once.

## 3. Pipeline notes

- Re-running: `pip` env with Pillow at
  /var/folders/wp/mfjhmzgj5vx35659rm6y4v2m0000gn/T/kilo/venv-img/bin/python,
  then `/…/python scripts/process-photos.py`. Downloads are cached in
  `artifacts/store-photos/cache/grabs-full/`; the ping fires once per photo.
- One pre-existing bug fixed on the way: `write_credits()` read a key
  (`photo_page`) that entries never carried - the credits writer had never
  actually run before this pass.
- The desk "zoom" support is generic: any choices.json entry (product, banner,
  hero, editorial) accepts `"zoom": <float>` for a tighter centre crop.

## 4. Watch-outs that still stand (from the previous pass)

- Re-measure home weight with real photos; the 800 KB gate held in the
  post-deploy check (see docs/STORE_VERIFY.md for the run numbers).
- The 2 cosmetic Woo ResizeObserver console warnings remain (block cart).
- The harness rotates the Woo key on every wp-setup run in compose; in-cluster
  the woo-secrets Secret prevents this - unchanged.
