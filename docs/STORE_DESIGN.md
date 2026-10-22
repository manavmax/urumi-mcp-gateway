# Store design - Loam & Ember (store v2)

Final design tokens for the storefront theme (`store/theme/urumi-store`). The
token family from main (ADR-037) is KEPT and refined, per the brief; the full
system lives in `theme.json` + the top of `assets/styles.css`.

## Brand

- Name: **Loam & Ember** (fictional; no real store, logo or copy used).
- Voice: small-batch, calm, specific. Claims match reality (cash on delivery,
  demo-store honesty).
- Niche: slow-made home and desk goods in six categories.

## Colour tokens

| Token | Value | Use |
| --- | --- | --- |
| page | `#ECEBE7` | page background (warm greige, kept) |
| card | `#FFFFFF` | cards, nav pill, newsletter block |
| tile | `#F3F2EF` | inner tiles, inputs, sold-out badge |
| ink | `#14171C` | all primary text, buttons, dark strip |
| muted | `#5F6673` | secondary text (7.0:1 on page) |
| accent (new) | `#A0522D` clay | sale badges, sale prices, small emphasis (4.7:1 on white) |
| accent-ink (new) | `#7E3F22` | accent text on light backgrounds |
| hairline | `rgba(20,23,28,.08)` | borders |
| hairline-strong | `rgba(20,23,28,.12)` | input borders |
| ring | `rgba(185,196,221,.55)` | focus rings |
| dusk gradient | `#B9C4DD -> #D9C8DC -> #EFCBBE` | hero backdrop (kept) |

Category tints (used by tiles and the product-art generator; accents appear
only as category tints):

| Category | Tint | Value |
| --- | --- | --- |
| Ceramics | periwinkle | `#B9C4DD` |
| Textiles | lilac | `#D9C8DC` |
| Candles & Care | peach | `#EFCBBE` |
| Desk & Paper | sand | `#E8DFD0` |
| Kitchen | sage (new) | `#D8E0D4` |
| Carry | clay-soft (new) | `#EBD9CC` |

Contrast gate: `scripts/verify-store-contrast.mjs` passes on every sampled page
and state (rest, hover, focus) after the redesign.

## Type

| Role | Face | Size / line-height |
| --- | --- | --- |
| Display (h1/h2, hero) | Instrument Serif (self-hosted woff2) | clamp(34px, 5vw, 56px) / 1.08 |
| Section titles | Instrument Serif | 30-36px / 1.15 |
| Body | Inter (self-hosted woff2) | 16px / 1.65 |
| Tile names | Inter 500 | 16px / 1.4 |
| Tile descriptions | Inter | 14px / 1.5 |
| Meta, badges | Inter 600 | 12px / 1.4 (no text below 12px anywhere) |
| Buttons | Inter 600 | 15px, letter-spacing 0.01em |

## Spacing scale

4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96 px (kept). Section rhythm: 96px
between front-page sections at 1440, 64px at 390. Content width: 1200px
(constrained), wide 1280px.

## Radii, shadow, motion

- Radii: 12px (inputs, small cards) / 24px (product cards) / 40px (hero art,
  large panels) / 999px (pills, buttons). Kept.
- Shadows: card `0 1px 2px rgba(20,23,28,.06), 0 8px 24px rgba(20,23,28,.06)`;
  lift on hover `0 2px 4px rgba(20,23,28,.08), 0 16px 40px rgba(20,23,28,.10)`.
  Very subtle by design.
- Motion: 160ms fast / 280ms slow, ease-out curve; hover lifts and reveals are
  the only movement; `prefers-reduced-motion: reduce` collapses all animation
  (verified: hero float measures 1e-05s under reduce).

## Accessibility

- AA contrast across the board (contrast gate green).
- Visible `:focus-visible` rings on every interactive element (2px ink ring +
  2px offset, or the lavender pill ring on dark).
- Colour never alone: sale/new/sold-out flags pair colour with text; stock
  states pair a dot with words.
- Reduced motion respected; zero third-party requests; both fonts self-hosted.
