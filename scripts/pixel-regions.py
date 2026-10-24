#!/usr/bin/env python3
"""Region-level pixel checks on the storefront screenshots in artifacts/store/.

A programmatic substitute for an eyeball pass: verifies that the mini-cart
drawer, the search suggestion panel, the mobile sticky add-to-cart bar, the
shop filter band and the category banner actually render in the captured
screenshots. Run after scripts/verify-store-polish.mjs.

    /path/to/venv/python scripts/pixel-regions.py

Exits non-zero on any failure. (The session that wrote this could not view
images - the model rejects image input - so the screenshots still deserve a
human look; these checks only catch structural problems.)
"""
import sys

from PIL import Image

A = "artifacts/store/"


def region(path, fx1, fy1, fx2, fy2):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    x0 = max(0, int(fx1 * w))
    y0 = max(0, int(fy1 * h))
    x1 = min(w, int(fx2 * w))
    y1 = min(h, int(fy2 * h))
    px = [im.getpixel((x, y)) for y in range(y0, y1, 3) for x in range(x0, x1, 3)]
    if not px:
        return None
    lum = sum(0.2126 * a + 0.7152 * b2 + 0.0722 * c for a, b2, c in px) / len(px)
    return round(lum), len(set(px))


ok = True


def check(name, cond, detail):
    global ok
    print(("PASS " if cond else "FAIL ") + name + ": " + detail)
    if not cond:
        ok = False


# 1. mini-cart drawer: right side of the viewport is the drawer (canvas bg over
#    the page) and carries the solid checkout button near its bottom.
dl, _ = region(A + "minicart-open-1440.png", 0.05, 0.30, 0.45, 0.70)
dr, _ = region(A + "minicart-open-1440.png", 0.60, 0.30, 0.97, 0.70)
check("minicart drawer region differs from page", abs(dl - dr) > 4, f"left_lum={dl} right_lum={dr}")
btn, _ = region(A + "minicart-open-1440.png", 0.65, 0.82, 0.95, 0.95)
check("minicart has a dark solid button region", btn < 190, f"btn_lum={btn}")

# 2. search suggestions panel: light panel band under the header on the right,
#    much lighter than the hero photograph below it.
panel = region(A + "search-open-1440.png", 0.70, 0.062, 0.96, 0.20)
hero = region(A + "search-open-1440.png", 0.70, 0.30, 0.96, 0.44)
check("suggestion panel renders over the hero", panel and hero and panel[0] - hero[0] > 25,
      f"panel_lum={panel[0] if panel else '-'} hero_lum={hero[0] if hero else '-'}")

# 3. mobile product: sticky bar at the bottom of the viewport - light bar with
#    a darker solid button area on its right.
bar, _ = region(A + "product-390.png", 0.05, 0.93, 0.95, 0.99)
btn390, _ = region(A + "product-390.png", 0.62, 0.93, 0.95, 0.99)
check("sticky ATC bar at bottom (390)", bar > 170 and btn390 < 200, f"bar_lum={bar} btn_lum={btn390}")

# 4. shop with filters: the head band (title, pills, chips, sort row) is a busy
#    light region.
band, uniq = region(A + "shop-filters-1440.png", 0.05, 0.05, 0.90, 0.22)
check("shop filter band renders", band > 150 and uniq > 150, f"band_lum={band} uniq={uniq}")

# 5. category: the banner photograph is truly photographic (high color variety).
_, buniq = region(A + "category-1440.png", 0.05, 0.05, 0.95, 0.25)
check("category banner is photographic", buniq > 300, f"uniq={buniq}")

# 6. cart: the totals summary exists (right sidebar region).
_, tuniq = region(A + "cart-1440.png", 0.60, 0.25, 0.95, 0.50)
check("cart totals summary present", tuniq > 60, f"uniq={tuniq}")

sys.exit(0 if ok else 1)
