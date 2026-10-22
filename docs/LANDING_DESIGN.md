# Landing page design tokens (ADR-081)

The landing page reuses the dashboard's token family so site and product read as one system.
Dark is the site default (dark-first per the brief); light mode mirrors the dashboard's light
theme. The single source of truth in code is `src/landing/styles.css`; this document records the
final values. No green accent anywhere. No webfonts: system stacks only, so nothing external is
requested and there is no layout shift.

## Colour (dark default / light override)

| Token | Dark (default) | Light (`[data-theme="light"]`) | Use |
|---|---|---|---|
| `--bg` | `#14161B` | `#ECEBE7` | page canvas |
| `--surface` | `#1C1F26` | `#FFFFFF` | cards, code card, footer |
| `--surface-2` | `#22262F` | `#F4F3EF` | wells, chips, stats, k8s-line |
| `--tint-soft` | `#1E2128` | `#F1F0EC` | hover washes |
| `--hairline` | `rgba(255,255,255,.08)` | `rgba(20,23,28,.08)` | dividers |
| `--hairline-strong` | `rgba(255,255,255,.14)` | `rgba(20,23,28,.14)` | input/table rules |
| `--text` | `#ECEDEF` | `#14171C` | primary text |
| `--muted` | `#9AA1AE` | `#5F6673` | secondary text |
| `--ink` | `#ECEDEF` | `#14171C` | primary button fill |
| `--ink-hover` | `#FFFFFF` | `#2A2E35` | primary hover |
| `--on-primary` | `#14171C` | `#FFFFFF` | text on the ink fill |
| `--on-tint` | `#14171C` | `#14171C` | text on accent tints, both themes |
| `--periwinkle` | `#7A8BAA` | `#B9C4DD` | list markers, sparkline stroke |
| `--sky` | `#8EAAC8` | `#DCE7F3` | sample-data chip fill |
| `--blush` | `#C49E98` | `#F4DCD8` | deny accents |
| `--ok-bg / --ok-text` | `#1E3A2E` / `#8ED4A8` | `#DDEDE4` / `#2F5D46` | ok badge (icon + text) |
| `--bad-bg / --bad-text` | `#3A1E1E` / `#E09090` | `#F4DCD8` / `#8A3B33` | permission_denied badge |
| `--tok-key` | `#A9BCD6` | `#3D5A80` | JSON keys in the code card |
| `--flow` | `#8EAAC8` | `#4F6F94` | SVG flow lines + arrowheads |
| `--flow-soft` | `rgba(142,170,200,.35)` | `rgba(79,111,148,.35)` | page-edge glow, back path |
| `--grad-a` | `#3E4A63 -> #5C5170 -> #7A5648` | `#B9C4DD -> #D9C8DC -> #EFCBBE` | ONE 3px strip on the code card top |

Gradient use is one 3px strip on the hero code card, nothing else (dashboard gradient rule).
Status badges always pair icon + text, never colour alone.

Measured minimums (WCAG, from scripts/landing-verify.mjs, 32 text pairs per theme): every gated
pair is >= 4.5:1 (>= 3:1 for large text). The one pair that failed the first run, the sample-data
chip (light text on mid-tone sky), was fixed by applying the dashboard's `--on-tint` rule (dark
ink on tints in both themes).

## Type scale

System stacks (`--font-sans`, `--font-mono`, same values as tokens.css). The landing scale extends
the dashboard's app scale upward for display sizes:

| Token | Value | Use |
|---|---|---|
| body | 16px / 1.55 | paragraphs |
| h1 | clamp(32px, 5.4vw, 54px), weight 800, -0.028em | hero |
| h2 | clamp(26px, 3.4vw, 32px), weight 750, -0.02em | section titles |
| h3 | 17-18px / 750 | feature + step titles |
| small | 12.5-14px | notes, chips, labels |
| code | 13.5px (12px at 560px) | code card, mono chips |

## Radii, shadows, spacing, motion

| Group | Value |
|---|---|
| Radii | card 24px, inner 14px, small 10px, pill 999px (dashboard family) |
| Shadow card | dark `0 1px 2px rgba(0,0,0,.25), 0 10px 30px rgba(0,0,0,.30)`; light `0 1px 2px rgba(20,23,28,.04), 0 10px 30px rgba(20,23,28,.05)` |
| Shadow lift (hover) | the card shadow with deeper spread |
| Section rhythm | `--section-pad: clamp(64px, 9vw, 112px)` between sections; 20px grid inside panels |
| Gutters | `--gutter: clamp(20px, 5vw, 48px)` |
| Motion | 150ms transitions only; flow lines animate `stroke-dashoffset` 1.8s linear; everything collapses under `prefers-reduced-motion` (verified: computed duration 1e-05s) |

## Density rules

Generous vertical rhythm BETWEEN sections, dense data INSIDE mockups: the audit table, stat tiles
and tool chips reuse the dashboard's 11-14px inner sizing. Both mockup panels carry a visible
"sample data" chip.

## Theme switching

Pre-paint script `theme-init.js` (external file, CSP-safe): stored choice in
`localStorage["landing-theme"]` inside try/catch, else `prefers-color-scheme`, else dark. The nav
toggle flips and stores the choice; `color-scheme` follows the theme.
