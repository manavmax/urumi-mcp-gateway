# Font credits (Loam & Ember store theme)

Self-hosted in `store/theme/urumi-store/assets/fonts/`, latin subset, variable
weight, `font-display: swap`, served from the store-assets image. No CDN, no
external font requests at runtime.

| Family | File | Source package | Version | Licence |
| --- | --- | --- | --- | --- |
| Newsreader Variable | `newsreader-latin-wght-normal.woff2` | `@fontsource-variable/newsreader@5.3.0` | 5.3.0 | SIL Open Font License 1.1 |
| Newsreader Variable (italic) | `newsreader-latin-wght-italic.woff2` | `@fontsource-variable/newsreader@5.3.0` | 5.3.0 | SIL Open Font License 1.1 |
| Hanken Grotesk Variable | `hanken-grotesk-latin-wght-normal.woff2` | `@fontsource-variable/hanken-grotesk@5.3.0` | 5.3.0 | SIL Open Font License 1.1 |

## How these files were produced

- Installed with npm into a temporary folder outside the repository:
  `@fontsource-variable/newsreader` and `@fontsource-variable/hanken-grotesk`.
- Copied only the `*-latin-wght-*.woff2` variable-font files (weight axis,
  latin unicode range) into the theme. No other subsets ship.
- The npm packages and temp folder live outside the repository; only the
  woff2 binaries are committed here.

## Licence notes

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
