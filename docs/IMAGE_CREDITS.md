# Image credits - Loam & Ember store (store v2)

**Every image in `store/images/` is original artwork generated for this
project** by `scripts/gen-store-images.py` (Pillow). There are no third-party
assets, no stock photography, no AI-upscaled or scraped images, no logos, no
photographs of people, and no likenesses of identifiable people.

## How the artwork is made

- Flat illustrated product renders drawn programmatically with Pillow:
  parametric shape functions (vessels, bowls, plates, folded textiles, candles,
  bags, boards and so on) composed in a 0-100 unit space at 1000x1000 px.
- Palettes are derived from the theme's category tints (docs/STORE_DESIGN.md);
  light direction, contact shadow and a subtle vignette are applied uniformly.
- Per SKU the generator writes:
  - `<SKU>.png` main tile,
  - `<SKU>-2.png` alternate composition on a tinted ground,
  - `<SKU>-3.png` detail crop (quantised PNG-8),
  - `<SKU>-4.png` context scene (featured/new products only),
  - `<SKU>-cutout.png` transparent cutout for the hero and category tiles.
- Existing files are never regenerated unless `--force` is passed.

## License

Original work created for this repository. To the extent any copyright can
subsist in programmatically generated flat illustration, it is held by this
project and the repository's license applies. No attribution is required
beyond this note.

## Budgets (verified 2026-10-22)

- 155 PNG files, longest side 1000 px (<= the 1000 px cap).
- Total 1.9 MB (<= the 12 MB cap); no single file over 120 KB.
- Images ship inside the store-assets image and are sideloaded from local
  files by the wp-setup seed; the storefront makes zero external image
  requests (offline at runtime, verified by the zero-third-party gate).

To regenerate: `python3 scripts/gen-store-images.py [--force]` (needs Pillow;
the repo's usual venv has it).
