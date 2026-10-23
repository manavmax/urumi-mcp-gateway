# Image credits - Loam & Ember store

**Status: photography pending curation.** The previous pass shipped original
generated artwork; that artwork is retired (docs/DECISIONS.md ADR-076) and
every product photograph is now sourced from **Unsplash** under the
**Unsplash License** (free to use, commercial and non-commercial, no
permission needed; https://unsplash.com/license).

The session that rebuilt this theme could not view images, so per its brief
it did NOT choose photographs (docs/DECISIONS.md ADR-078). Until curation
runs:

- `store/images/` contains no photographs (the seed attaches no images and
  the storefront shows neutral placeholder frames), and
- this file and the storefront `/image-credits/` page carry the licence and
  sourcing rules only, no per-photo rows.

## How credits are produced (after curation)

1. `scripts/fetch-unsplash.py` caches API searches (gitignored) and never
   prints the Access Key (`.unsplash_key`, gitignored, read only inside
   scripts).
2. A curator picks photos from the candidate sheets
   (`artifacts/store-photos/sheets/`), writing
   `artifacts/store-photos/choices.json` (gitignored).
3. `scripts/process-photos.py` downloads each chosen photo (calling its
   `links.download_location` endpoint first, as Unsplash requires), crops
   4:5 at 1200px, encodes webp q80 under 150KB, and then rewrites:
   - `artifacts/store-photos/manifest.json` (working copy, gitignored)
   - `store/photos-manifest.json` (committed copy; ships in the store-assets
     image and renders the `/image-credits/` page)
   - this file, `docs/IMAGE_CREDITS.md`, with one row per shipped file
   - `artifacts/store-photos/contact-sheet.png` (gitignored) for review

## Per-photo table

| File | SKU | Photographer | Photo | Licence |
| --- | --- | --- | --- | --- |

(Empty until curation. Every shipped photograph will carry: no identifiable
faces, no visible text or logos, no brand names, no watermarks -
docs/STORE_DESIGN.md section 6.)

The storefront footer links "Photography from Unsplash." to
`/image-credits/`.
