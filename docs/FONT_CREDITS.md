# Font credits

All fonts are self-hosted (no CDN, no external font requests) and licensed under the SIL Open Font License 1.1. Landing page and store theme are listed separately.

## Landing page font credits

The landing page self-hosts two typefaces as woff2, latin subset only (ADR-086).
No font CDN, no external font request; the fonts are served from `src/landing/fonts/`
by the landing nginx image, same origin as the page.

| Family | File | Subset | Size | Licence | Source package |
|---|---|---|---|---|---|
| Inter Variable | `inter-latin-wght-normal.woff2` | latin, wght axis (normal) | 48,256 B | SIL Open Font License 1.1 | `@fontsource-variable/inter` |
| DM Mono | `dm-mono-latin-400-normal.woff2` | latin, weight 400 (normal) | 14,820 B | SIL Open Font License 1.1 | `@fontsource/dm-mono` |
| DM Mono | `dm-mono-latin-500-normal.woff2` | latin, weight 500 (normal) | 14,988 B | SIL Open Font License 1.1 | `@fontsource/dm-mono` |

### Provenance

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

### How they are loaded

- The two main files (Inter Variable, DM Mono 400) are preloaded with
  `<link rel="preload" as="font" type="font/woff2" crossorigin>` in
  `src/landing/index.html`; DM Mono 500 loads on use.
- `@font-face` declarations live in `src/landing/styles.css` with
  `font-display: swap`, so text renders immediately in the fallback stack.
- The landing CSP keeps `font-src 'self'`; fonts add no external requests.

## Font credits (Loam & Ember store theme)

Self-hosted in `store/theme/urumi-store/assets/fonts/`, latin subset, variable
weight, `font-display: swap`, served from the store-assets image. No CDN, no
external font requests at runtime.

| Family | File | Source package | Version | Licence |
| --- | --- | --- | --- | --- |
| Newsreader Variable | `newsreader-latin-wght-normal.woff2` | `@fontsource-variable/newsreader@5.3.0` | 5.3.0 | SIL Open Font License 1.1 |
| Newsreader Variable (italic) | `newsreader-latin-wght-italic.woff2` | `@fontsource-variable/newsreader@5.3.0` | 5.3.0 | SIL Open Font License 1.1 |
| Hanken Grotesk Variable | `hanken-grotesk-latin-wght-normal.woff2` | `@fontsource-variable/hanken-grotesk@5.3.0` | 5.3.0 | SIL Open Font License 1.1 |

### How these files were produced

- Installed with npm into a temporary folder outside the repository:
  `@fontsource-variable/newsreader` and `@fontsource-variable/hanken-grotesk`.
- Copied only the `*-latin-wght-*.woff2` variable-font files (weight axis,
  latin unicode range) into the theme. No other subsets ship.
- The npm packages and temp folder live outside the repository; only the
  woff2 binaries are committed here.

### Licence notes

- Newsreader: Copyright 2020 The Newsreader Project Authors
  (https://github.com/productiontype/Newsreader), licensed under the SIL Open
  Font License, Version 1.1. Upstream licence text ships with the fontsource
  package (`LICENSE`).
- Hanken Grotesk: Copyright 2021 The Hanken Grotesk Project Authors
  (https://github.com/marcologous/hanken-grotesk), licensed under the SIL
  Open Font License, Version 1.1.
- SIL OFL 1.1 permits bundling and redistribution in web projects, including
  commercial use, provided the fonts are not sold by themselves and reserved
  names are respected. Both families meet the store requirement of a freely
  licensed, self-hostable typeface.
- Full licence texts are distributed with the fontsource packages
  (node_modules/@fontsource-variable/<family>/LICENSE) and upstream at
  https://openfontlicense.org .
