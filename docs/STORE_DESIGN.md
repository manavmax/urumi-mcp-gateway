---
version: alpha
name: Loam & Ember Store
description: |
  A quiet, gallery like online shop for `slow-made` home and desk goods. A warm,
  neutral palette of linen whites and soft taupes frames real product photography.
  Typography is measured: a text serif for warmth and a small, tracked sans for the
  interface. The design avoids decoration and celebrates negative space, sharp
  edges and the tactile quality of materials. The shop is a demo store: no real
  orders ship.
source:
  note: "Design language derived from an analysed reference design file. Tokens are reused with small tweaks. No name, logo, copy or photography of the reference site is used."
colors:
  canvas: "#FBFBF9"
  `surface-alt`: "#F4F2EC"
  `surface-raised`: "#ECEAE4"
  ink: "#262525"
  body: "#333333"
  `neutral-1`: "#999999"
  `neutral-2`: "#B8B8B8"
  `neutral-3`: "#3E3E3D"
  `neutral-4`: "#4C4C4C"
  taupe: "#D2C5B7"
  beige: "#E8DFD0"
  hairline: "#E1E1E0"
  `hover-fill`: "#1A1A1A"
  overlay: "rgba(72, 64, 54, 0.20)"
  # No red, green or orange anywhere. Status is shown with words, weight and underline.
typography:
  display: { fontFamily: "Newsreader Variable", fontSize: 40px, fontWeight: 500, lineHeight: 1.1, letterSpacing: -0.2px }
  `heading-xl`: { fontFamily: "Newsreader Variable", fontSize: 28px, fontWeight: 500, lineHeight: 1.2 }
  `heading-lg`: { fontFamily: "Newsreader Variable", fontSize: 24px, fontWeight: 500, lineHeight: 1.2 }
  `heading-md`: { fontFamily: "Newsreader Variable", fontSize: 22px, fontWeight: 500, lineHeight: 1.2 }
  `heading-sm`: { fontFamily: "Newsreader Variable", fontSize: 20px, fontWeight: 500, lineHeight: 1.2 }
  `body-lg`: { fontFamily: "Newsreader Variable", fontSize: 18px, fontWeight: 500, lineHeight: 1.35 }
  body md: { fontFamily: "Newsreader Variable", fontSize: 16px, fontWeight: 500, lineHeight: 1.35 }
  `label-caps`: { fontFamily: "Hanken Grotesk Variable", fontSize: 12px, fontWeight: 400, lineHeight: 1.5, letterSpacing: 0.48px, textTransform: uppercase }
  button: { fontFamily: "Hanken Grotesk Variable", fontSize: 13px, fontWeight: 400, lineHeight: 1.35, letterSpacing: 0.26px, textTransform: uppercase }
  ui md: { fontFamily: "Hanken Grotesk Variable", fontSize: 16px, fontWeight: 500, lineHeight: 1.15 }
  `ui-sm`: { fontFamily: "Hanken Grotesk Variable", fontSize: 13px, fontWeight: 400, lineHeight: 1.35, letterSpacing: 0.26px }
  caption: { fontFamily: "Hanken Grotesk Variable", fontSize: 12px, fontWeight: 400, lineHeight: 1.5, letterSpacing: 0.24px }
  `caption-xs`: { fontFamily: "Hanken Grotesk Variable", fontSize: 11px, fontWeight: 400, lineHeight: 1.5, letterSpacing: 0.22px }
  # TWEAK: the reference fonts (Plantin Infant, Monument Grotesk) are commercial and cannot be shipped.
  # Newsreader and Hanken Grotesk are OFL licensed. Self host latin woff2 only.
  # TWEAK: a 40px display size is allowed for the home hero only. Everything else keeps the reference scale.
rounded: { none: 0px }
spacing: { xxs: 4px, xs: 8px, sm: 12px, md: 16px, lg: 20px, xl: 24px, xxl: 28px, xxxl: 32px, section: 36px, band: 40px }
section padding y: "clamp(56px, 8vw, 120px)"
borderWidths: { thin: 1px }
elevation: "color blocking, no shadows"
motion:
  duration: { fast: 200ms, base: 300ms, slow: 500ms }
  easing: "`cubic-bezier`(0.2, 0.7, 0.2, 1)"
components:
  button outline: { typography: "{typography.button}", textColor: "{colors.body}", border: "1px solid {colors.body}", height: 44px, padding: "12px 16px", rounded: "{rounded.none}", hover: "background {colors.`hover-fill`}, border {colors.`hover-fill`}, text {colors.canvas}" }
  button solid: { typography: "{typography.button}", backgroundColor: "{colors.body}", textColor: "{colors.canvas}", height: 44px, padding: "12px 24px", rounded: "{rounded.none}", hover: "background {colors.`hover-fill`}" }
  button text: { typography: "{typography.button}", textColor: "{colors.body}", padding: "7px 0", hover: "opacity 0.7, underline" }
  input: { typography: "{typography.`ui-sm`}", border: "1px solid {colors.`neutral-2`}", height: 44px, padding: "0 12px", rounded: "{rounded.none}", focus: "border {colors.ink}, 1px inner shadow rgb(235,235,235)" }
  card: { backgroundColor: "transparent", border: none, rounded: "{rounded.none}", padding: none }
  badge text: { typography: "{typography.`label-caps`}", textColor: "{colors.`neutral-3`}", note: "plain tracked text, no fill, no colour" }
  nav link: { typography: "{typography.ui md}", textColor: "{colors.`neutral-3`}", hover: "ink, underline" }
  focus: { outline: "2px solid {colors.ink}", outlineOffset: 2px, note: "always visible" }
  disabled: { opacity: 0.4, textColor: "{colors.`neutral-1`}" }
breakpoints:
  - { width: 375, columns: 4, productGridColumns: 2, paddingX: 16 }
  - { width: 768, columns: 4, productGridColumns: 3, paddingX: 24 }
  - { width: 1024, columns: 7, productGridColumns: 4, paddingX: 32 }
  - { width: 1440, columns: 7, productGridColumns: 4, containerMax: 1360 }
---

# Loam & Ember store: design spec

This file is the single source of truth for the storefront theme. Where it disagrees with
earlier store notes (docs/STORE_DESIGN.md before this version), this file wins. The previous
look (clay accent, rounded cards, generated illustrations) is retired.

## 1. Atmosphere

Calm, honest and gallery like. The canvas is warm off white, sections alternate with a slightly
warmer band, and the products are the only thing that carries colour. Everything else is
neutral. There are no shadows, no rounded corners, no gradients except one soft warm overlay
on the hero photograph, and no decorative graphics. Space is a material: generous margins let
the photography breathe.

Key characteristics:
- Warm neutral palette: `#FBFBF9` canvas, `#F4F2EC` bands, ink `#262525`, taupe and beige used sparingly as block colours.
- Two typefaces: Newsreader (serif) for headings, product names and descriptions; Hanken Grotesk (sans) for navigation, buttons, labels, prices and captions.
- Sharp corners everywhere (radius 0). One pixel hairlines. Depth only by colour blocking.
- Interaction is quiet: opacity shifts, underlines, a slow image zoom, outline buttons that fill on hover.

## 2. Colour roles

- Canvas `#FBFBF9`: page background. `Surface-alt` `#F4F2EC`: alternate bands, summary boxes, footer. Raised `#ECEAE4`: hover rows.
- Ink `#262525`: headings and emphasis. Body `#333333`: text and primary borders and button fills. `Neutral-3` `#3E3E3D`: nav text, labels.
- `Neutral-1` `#999999`: disabled and muted text, struck through old prices. `Neutral-2` `#B8B8B8`: input borders and fine hints.
- Taupe `#D2C5B7` and beige `#E8DFD0`: block colours behind category tiles or text panels when a photo is not used. Never for text.
- No red, green or orange. Sale, sold out and errors are communicated with words (for example "Sale", "Sold out", "Error:"), weight and underline, never with a colour.

## 3. Typography

- Headings: Newsreader, weight 500, tight and small and elegant (20 to 28px). Hero display only: 40px on desktop, 30px on mobile.
- Body and product descriptions: Newsreader 16 to 18px, `line-height` 1.35.
- Interface: Hanken Grotesk. Labels and buttons are uppercase 12 to 13px with 0.26 to 0.48px tracking. Prices are Hanken Grotesk 14 to 16px, tabular numbers.
- Never mix the two families inside one paragraph. Never use bold headings; use size and space.
- Self host `@fontsource-variable/newsreader` and `@fontsource-variable/hanken-grotesk` (latin subset woff2, `font-display: swap`) in the `store-assets` image. No CDN. Record licences in docs/FONT_CREDITS.md.

## 4. Components

- Outline button (primary action): transparent, 1px body colour border, uppercase 13px, 12px by 16px padding. Hover: fill `#1A1A1A`, text `#FBFBF9`, 200ms.
- Solid button (only for Add to cart and Place order): body colour fill, canvas text. Hover darkens to `#1A1A1A`.
- Text button: uppercase 13px, no border, hover underline and opacity 0.7.
- Inputs, selects, quantity stepper: 44px high, 1px `neutral-2` border, radius 0, focus border ink. Labels above in `label-caps`.
- Product card: no border, no fill. Image first, then name in Newsreader 16px, then price in Hanken Grotesk 14px. A plain text badge (SALE, SOLD OUT, NEW) in `label-caps` above the name when needed. Old price struck through in `neutral-1` next to the new one.
- Navigation: Hanken Grotesk 16px, `neutral-3`, hover ink with underline. Mobile: a menu button opens a full screen overlay on canvas with large Newsreader links.
- Focus: 2px solid ink outline with 2px offset on every interactive element. Never remove it.
- Disabled: opacity 0.4 and `neutral-1` text.

## 5. Page blueprints

All pages sit in a 1360px max container (1200px content) with the 4 and 7 column rhythm from the front matter. Sections alternate canvas and `surface-alt` with 56 to 120px vertical padding.

1. **Header** (canvas, hairline bottom). Wordmark "Loam & Ember" in Newsreader at left, nav: Shop, Collections (a simple dropdown of the 6 categories), About, Shipping. Right: Search, Account, Cart with a count in plain text. Sticky on scroll with a canvas background.
2. **Home hero**: a full bleed lifestyle photograph (real photo, quiet still life) with the 20 percent warm overlay, a short Newsreader display headline and one outline button "Shop the collection". Text sits on a calm area of the photo, contrast AA verified.
3. **Intro statement** (canvas): one centred paragraph in Newsreader 22px about the shop, followed by a text button.
4. **Collections** (`surface-alt`): six category tiles in a 3 by 2 grid on desktop, 2 by 3 on mobile. Each is a real photo with the category name in `label-caps` below. Image zoom 1.03 on hover.
5. **New and featured** (canvas): a 4 column product grid (2 on mobile), 8 products, with a text button "View all".
6. **Editorial split** (`surface-alt`): one photo on one side, a short text block on the other (materials and care), outline button.
7. **Details strip** (canvas): three short text items: Cash on delivery, Packed by hand, 14-day returns. No icons.
8. **Footer** (`surface-alt`): four columns (Shop, Help, About, Legal), a small line "A demo store. No real orders are shipped." and "Photography from Pexels." plus the real credits link.
9. **Shop archive**: title in Newsreader 28px, a quiet filter row of category text links (active one underlined) and a sort select on the right, then the 4 column grid (3 at tablet, 2 at mobile) and plain text pagination. Cards use a consistent 4:5 image crop. Category archives open with a wide banner photograph (banner-<slug>.webp from the catalog category's "image", full bleed, eager) above the title; without a banner file the head renders exactly as before.
10. **Product page**: 7 column grid. Left (4 columns): a large image with vertical thumbnails on desktop and a swipeable strip on mobile. Right (3 columns): breadcrumb in `label-caps`, title in Newsreader 28px, price, a two or three line description in Newsreader, variation selects, quantity, a full width solid "Add to cart" button, then plain accordions: Details, Dimensions and care, Shipping and returns. Below: "You may also like" with 4 products.
11. **Cart**: a clean table (image, name, price, quantity, line total), a summary box on `surface-alt`, a solid "Proceed to checkout" button. Empty cart: a calm sentence and a text button.
12. **Checkout**: two columns on desktop. Left: billing fields with `label-caps` labels and 44px inputs. Right: an order summary on `surface-alt` with a clear Cash on delivery choice (radio) and a solid "Place order" button. Validation: an inline sentence beginning "Error:" in ink, with a 1px ink left border, never red.
13. **Order received**: a calm confirmation with order number, items, total and payment method in a `hairline-ruled` list.
14. **Search results, 404, My account**: same grid and typography, minimal. The 404 has a short sentence, a search field and a text button back to the shop.

## 6. Photography direction (real photographs only)

- Real photographs only. No illustrations, no renders, no AI generated images, no flat vector art.
- Soft natural daylight, neutral backdrops (linen, plaster, pale oak, stone), one product or a small still life, generous negative space. Consistent white balance and mood across the catalogue.
- Grid images are cropped to 4:5, long side 1200px, webp quality about 80, each file 150KB or less. Provide 600px and 1200px variants and use `srcset` with `loading="lazy"` (the hero eager).
- No identifiable faces, no visible text, no logos or brand names on products, no watermarks.
- Each product has a main image; a second image should be a different real photo or a detail crop of the same photo. Never show a different product than the one named.
- Licence: only photographs under a licence that allows free reuse (Pexels, Unsplash or CC0). Record photographer, photo URL and licence per file in docs/IMAGE_CREDITS.md and in a machine readable manifest.

## 7. Copy voice (no marketing slop)

- Short, plain, concrete sentences. State material, size, finish and how to care for it.
- Banned words and habits: elevate, curated, seamless, unlock, perfect for any occasion, must have, game changer, exclamation marks, emojis, rhetorical questions, filler superlatives, em dashes.
- Product names are two to four words and match what the photograph shows. Descriptions mention only what is visible or plainly true of the object (material, colour, form, use). No invented awards, certifications or origin claims.
- Prices are plain numbers. Dimensions in millimetres or centimetres.

## 8. Motion

- Page and section changes are instant. Product images zoom 1.03 over 500ms on hover inside an overflow hidden frame. Links underline over 200ms. Buttons fill over 200ms.
- Mobile menu overlay fades in over 300ms. `prefers-reduced-motion: reduce` disables the zoom and the fade.

## 9. Responsive

- 375px: single column content, product grids 2 columns, section padding 16px, hero text 30px. 768px: 3 column grids. 1024px and up: 4 column grids, full navigation, 1200px content.
- Touch targets at least 44px. No horizontal scroll at 375, 768, 1024 or 1440.

## 10. Do and do not

Do: let the photographs lead, keep surfaces warm and flat, use hairlines and spacing for structure, keep every state visible and subtle, keep focus rings.
Do not: add rounded corners, shadows, gradients (except the hero overlay), accent colours, badges with colour fills, icons that decorate, generated artwork, stock photo clichés, stacked competing calls to action, or any text that sounds like an advertisement.