# Design decisions log (STAGE 0)

Append-only. One entry per decision, newest last.

## 2026-10-14: palette moved from sage green to dusty blue (calm English pastel)

**What changed.** The dashboard palette is now: page `#EEEDE8` warm greige, cards `#FFFFFF`,
sidebar and wells `#F6F5F1`, ink `#1E2430`, muted `#7A8190`, hairline `#E4E2DB`, one primary
dusty blue `#4F6F94` (hover `#425F82`, soft tint `#DCE7F3`), and five accent tints for cards,
chart bars and avatars: butter `#F3E6C4`, blush `#F4DCD8`, lilac `#E4DEF1`, sky `#DCE7F3`,
sand `#EADFCB`. Status badges: Connected mint `#DDEDE4` with text `#2F5D46`, Unreachable blush
`#F4DCD8` with text `#8A3B33`, Disabled grey `#E9E8E3` with text `#6B7280`, always icon plus text.

**Why.** The brief asked for a calm English pastel palette matching the reference screenshots and
for the sage green to be removed. A single dusty blue primary keeps the UI calm at high
information density while giving links, active nav and primary buttons one clear accent.
Measured contrast: primary on white 5.21:1 and white on primary 5.21:1 (AA for normal text),
ink on white 15.55:1, Connected 6.24:1, Unreachable 5.84:1.

**Alternatives considered.**
- Keeping sage green as the primary: rejected by the brief; it also read as "health status" and
  competed with the mint Connected badge.
- Warm terracotta or oxblood primary: closer to the reference art but too heavy for dense data
  tables and for long sessions.
- Multi-hue categorical palette for charts: rejected for calm; charts now use the five accent
  tints plus the primary, with semantic error text colour only for error caps.
- Dark mode token set: still out of scope, listed as a needs-decision item.

**Known trade-off.** Two requested colours measure below 4.5:1 for small text: muted `#7A8190`
is 3.91:1 on white and 3.34:1 on the greige, and Disabled text `#6B7280` on `#E9E8E3` is
3.94:1. They pass AA for large text only. The mockups keep the requested values and flag the
pair; Stage 1 should either darken muted to about `#5F6673` or treat those strings as decorative.

## 2026-10-15: STAGE 0.6, bento pattern with ink primary and controlled gradients

**What changed.** The mockups move to the reference pattern: warm greige canvas `#ECEBE7`, white
borderless cards (radius 24, inner chips 14), layered shadows `0 1px 2px rgba(20,23,28,.04), 0 10px 30px rgba(20,23,28,.05)`,
ink `#14171C` as the only primary (buttons, active nav, segmented active, toggles), muted `#5F6673`,
Disabled badge text `#565D69`, Overview rebuilt as a bento grid (four equal stat tiles with one
gradient hero, wide chart with floating mini-cards, half-ring gauge, my-account card, activity with
accent bars, tools overview, fleet status), greeting page header with a pill search field and a
round ink search button, a floating pill sidebar (72px icon-only, expands to 248px as an overlay on
hover or focus-within with an 80ms intent delay, 20ms label stagger, 150ms collapse delay), a chat
page with a centered gradient-glow empty state, suggestion cards, a wide pill composer with a round
ink send button and a right-hand chat history panel, and a login re-skin on a soft gradient glow.

**Why.** The brief locked logo A, required the pastel bento and floating-pill-sidebar pattern from
the new references (pattern, not content), ink primary actions with gradient reserved for one hero
tile, the gauge or chart fill, the login art, the chat glow and the page-edge glow.

**Gradient options.** `design/mockups/palette-options.html` renders the Overview hero and gauge in
three non-green gradients: A "Dusk" (`#B9C4DD`, `#D9C8DC`, `#EFCBBE`; ink on stops 10.27 / 11.33 /
11.94 to 1), B "Mist" (`#A9BBD3`, `#CFE0EE`, `#F3EAD8`; 9.18 / 13.30 / 15.03), C "Rose sand"
(`#E3BFB8`, `#EADFCB`, `#D5E0EC`; 10.62 / 13.61 / 13.43). A "Dusk" is recommended and ships as the
working default; the final choice is still with the user.

**Contrast.** All pairs now pass AA for normal text: ink on white 17.96:1, muted `#5F6673` on white
5.78:1 and on greige 4.84:1, Disabled `#565D69` on `#E9E8E3` 5.41:1, Connected 6.24:1, Unreachable
5.84:1, white on ink 17.96:1. This closes the two below-threshold pairs flagged in the 0.5 entry.
