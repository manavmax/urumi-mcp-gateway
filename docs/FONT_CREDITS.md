# Landing page font credits

The landing page self-hosts two typefaces as woff2, latin subset only (ADR-086).
No font CDN, no external font request; the fonts are served from `src/landing/fonts/`
by the landing nginx image, same origin as the page.

| Family | File | Subset | Size | Licence | Source package |
|---|---|---|---|---|---|
| Inter Variable | `inter-latin-wght-normal.woff2` | latin, wght axis (normal) | 48,256 B | SIL Open Font License 1.1 | `@fontsource-variable/inter` |
| DM Mono | `dm-mono-latin-400-normal.woff2` | latin, weight 400 (normal) | 14,820 B | SIL Open Font License 1.1 | `@fontsource/dm-mono` |
| DM Mono | `dm-mono-latin-500-normal.woff2` | latin, weight 500 (normal) | 14,988 B | SIL Open Font License 1.1 | `@fontsource/dm-mono` |

## Provenance

- Packages were installed into a temporary folder OUTSIDE this repository
  (`npm install @fontsource-variable/inter @fontsource/dm-mono`), and only the
  latin-subset woff2 files listed above were copied into `src/landing/fonts/`.
  No other file from either package ships in the repo or the image.
- Both packages state `"license": "OFL-1.1"` in their `package.json`.
- Inter is copyright The Inter Project Authors
  (https://github.com/rsms/inter), released under the SIL Open Font License 1.1.
- DM Mono is copyright The DM Mono Project Authors
  (https://github.com/googlefonts/dm-mono), released under the SIL Open Font
  License 1.1.
- The SIL Open Font License 1.1 full text:
  https://openfontlicense.org/open-font-license-official-text/

## How they are loaded

- The two main files (Inter Variable, DM Mono 400) are preloaded with
  `<link rel="preload" as="font" type="font/woff2" crossorigin>` in
  `src/landing/index.html`; DM Mono 500 loads on use.
- `@font-face` declarations live in `src/landing/styles.css` with
  `font-display: swap`, so text renders immediately in the fallback stack.
- The landing CSP keeps `font-src 'self'`; fonts add no external requests.
