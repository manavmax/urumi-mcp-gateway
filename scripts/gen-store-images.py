#!/usr/bin/env python3
"""Generate original illustrated product images for the Urumi store.

Reads store/products.json and, for every product SKU, renders a 1200x1200 PNG
tile on a soft neutral background with a consistent light direction and a soft
contact shadow, plus a transparent <sku>-cutout.png for the hero and category
tiles. All artwork is original flat illustration drawn with Pillow: no
third-party assets, no copyrighted likenesses, no photos.

The seed respects existing files: if <sku>.png already exists it is NOT
regenerated (pass --force to overwrite), so the owner can later drop in better
photos with the same name and no code changes. Any file in store/images with the
same name is picked up by the wp-setup job unchanged.

Run: ../../.venv/bin/python scripts/gen-store-images.py   (from repo root, or
      .venv/bin/python scripts/gen-store-images.py from anywhere)
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCTS_JSON = os.path.join(ROOT, "store", "products.json")
OUT_DIR = os.path.join(ROOT, "store", "images")

SIZE = 1200
UNIT = SIZE / 100.0
FORCE = "--force" in sys.argv

# Theme family (same family as the dashboard tokens; no colour literal used in
# the shipped CSS outside theme.json - these only drive the artwork here).
TILE_BG = (243, 242, 239)      # tile #F3F2EF
INK = (20, 23, 28)             # ink #14171C
PERIWINKLE = (185, 196, 221)
LILAC = (217, 200, 220)
PEACH = (239, 203, 190)
SAND = (232, 223, 208)
CREAM = (244, 241, 234)
STONE = (208, 202, 192)
CHARCOAL = (82, 88, 98)
WHITE = (250, 250, 250)
NAVY = (72, 80, 96)


def u(v):
    """Convert from 0..100 units to pixels."""
    return v * UNIT


def soft_shadow(draw: ImageDraw.ImageDraw, cx, cy, rx, ry, alpha=46) -> None:
    """Contact shadow as a blurred ellipse; light direction implied top-left."""
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(20, 23, 28, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=u(1.5)))
    draw._image.alpha_composite(layer)


def overlay_light(draw: ImageDraw.ImageDraw) -> None:
    """Consistent light direction: a very soft top-left radial highlight."""
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse([-u(30), -u(30), u(90), u(90)], fill=(255, 255, 255, 26))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=u(14)))
    draw._image.alpha_composite(layer)


def rr(draw, x0, y0, x1, y1, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle([u(x0), u(y0), u(x1), u(y1)], radius=u(radius),
                           fill=fill, outline=outline, width=int(u(width)))


def rounded_polygon(draw, points, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(points, radius=radius, fill=fill, outline=outline, width=width)


# ---------------------------------------------------------------------------
# Product illustrations. Each function draws on a shared 100x100 unit canvas.
# ---------------------------------------------------------------------------

def draw_tee(draw):
    # body
    rr(draw, 35, 28, 65, 78, 6, fill=CREAM, outline=(196, 189, 178, 255), width=2)
    # sleeves
    rr(draw, 20, 30, 39, 58, 6, fill=CREAM, outline=(196, 189, 178, 255), width=2)
    rr(draw, 61, 30, 80, 58, 6, fill=CREAM, outline=(196, 189, 178, 255), width=2)
    # neck
    draw.arc([u(42), u(24), u(58), u(44)], start=180, end=360, fill=(196, 189, 178, 255), width=int(u(2)))
    # collar
    rr(draw, 44, 27, 56, 37, 4, fill=STONE)
    # chest pocket line
    draw.rounded_rectangle([u(44), u(44), u(56), u(58)], radius=u(2),
                           outline=(196, 189, 178, 255), width=int(u(1.5)), fill=None)


def draw_hoodie(draw):
    # body
    rr(draw, 34, 30, 66, 80, 6, fill=NAVY, outline=(54, 60, 72, 255), width=2)
    # sleeves
    rr(draw, 18, 32, 36, 60, 6, fill=NAVY, outline=(54, 60, 72, 255), width=2)
    rr(draw, 64, 32, 82, 60, 6, fill=NAVY, outline=(54, 60, 72, 255), width=2)
    # kangaroo pocket
    rr(draw, 38, 52, 62, 72, 8, fill=(54, 60, 72, 255))
    # hood
    draw.ellipse([u(34), u(20), u(66), u(48)], fill=NAVY, outline=(54, 60, 72, 255), width=int(u(2)))
    # drawstrings
    draw.line([u(44), u(40), u(44), u(52)], fill=(220, 214, 202, 255), width=int(u(1.5)))
    draw.line([u(56), u(40), u(56), u(52)], fill=(220, 214, 202, 255), width=int(u(1.5)))


def draw_shoes(draw):
    # pair of sneakers in side-by-side view (left shoe, right shoe)
    # left shoe
    rr(draw, 20, 50, 52, 62, 6, fill=WHITE, outline=(196, 189, 178, 255), width=2)
    # toe cap
    draw.ellipse([u(18), u(50), u(34), u(62)], fill=WHITE, outline=(196, 189, 178, 255), width=int(u(2)))
    # sole
    rr(draw, 18, 60, 54, 66, 4, fill=(40, 44, 52, 255))
    # right shoe
    rr(draw, 56, 48, 88, 60, 6, fill=WHITE, outline=(196, 189, 178, 255), width=2)
    draw.ellipse([u(54), u(48), u(70), u(60)], fill=WHITE, outline=(196, 189, 178, 255), width=int(u(2)))
    rr(draw, 54, 58, 90, 64, 4, fill=(40, 44, 52, 255))
    # laces
    draw.line([u(30), u(56), u(36), u(54)], fill=(200, 194, 184, 255), width=int(u(1.5)))
    draw.line([u(36), u(54), u(40), u(56)], fill=(200, 194, 184, 255), width=int(u(1.5)))


def draw_cap(draw):
    # dome
    draw.pieslice([u(26), u(28), u(74), u(74)], start=180, end=360, fill=STONE,
                  outline=(120, 116, 108, 255), width=int(u(2)))
    # brim
    draw.pieslice([u(30), u(52), u(88), u(74)], start=0, end=180, fill=(120, 116, 108, 255))
    rr(draw, 28, 56, 86, 66, 5, fill=(120, 116, 108, 255))
    # seam lines
    draw.line([u(50), u(30), u(50), u(52)], fill=(140, 136, 126, 255), width=int(u(1.5)))
    draw.line([u(38), u(30), u(44), u(52)], fill=(140, 136, 126, 255), width=int(u(1.5)))
    draw.line([u(62), u(30), u(56), u(52)], fill=(140, 136, 126, 255), width=int(u(1.5)))
    # button on top
    draw.ellipse([u(47), u(25), u(53), u(31)], fill=(140, 136, 126, 255))


def draw_mug(draw):
    # body
    rr(draw, 32, 34, 68, 76, 5, fill=PEACH, outline=(196, 158, 142, 255), width=2)
    # handle
    draw.arc([u(66), u(42), u(78), u(66)], start=-90, end=90, fill=(196, 158, 142, 255), width=int(u(3)))
    # inner rim
    draw.ellipse([u(32), u(30), u(68), u(42)], fill=(250, 240, 234, 255),
                 outline=(196, 158, 142, 255), width=int(u(2)))
    draw.ellipse([u(40), u(34), u(60), u(40)], fill=(196, 158, 142, 255))
    # glaze streaks
    draw.line([u(42), u(52), u(44), u(70)], fill=(230, 200, 188, 255), width=int(u(2)))
    draw.line([u(54), u(46), u(52), u(72)], fill=(230, 200, 188, 255), width=int(u(2)))


def draw_candle(draw):
    # jar
    rr(draw, 34, 30, 66, 82, 5, fill=SAND, outline=(176, 158, 132, 255), width=2)
    # wax inside
    rr(draw, 36, 38, 64, 80, 4, fill=(244, 233, 214, 255))
    # lid
    rr(draw, 30, 22, 70, 32, 4, fill=(120, 116, 108, 255), outline=(100, 96, 88, 255), width=2)
    # wick
    draw.line([u(50), u(32), u(50), u(38)], fill=(70, 64, 58, 255), width=int(u(1.5)))
    # flame
    draw.ellipse([u(46), u(26), u(54), u(34)], fill=(250, 224, 170, 255))
    # label
    rr(draw, 40, 50, 60, 66, 2, fill=(232, 223, 208, 255), outline=(176, 158, 132, 255), width=1)


def draw_throw(draw):
    # folded blanket: overlapping rectangles
    rr(draw, 30, 40, 70, 62, 5, fill=PERIWINKLE, outline=(150, 162, 190, 255), width=2)
    rr(draw, 32, 44, 68, 66, 5, fill=(170, 182, 208, 255), outline=(150, 162, 190, 255), width=2)
    rr(draw, 34, 48, 66, 70, 5, fill=PERIWINKLE, outline=(150, 162, 190, 255), width=2)
    # fringe
    for i in range(8):
        x = 36 + i * 4
        draw.line([u(x), u(68), u(x), u(74)], fill=(150, 162, 190, 255), width=int(u(1.2)))


def draw_tote(draw):
    # bag body
    rr(draw, 32, 42, 68, 78, 4, fill=SAND, outline=(176, 158, 132, 255), width=2)
    # handles
    draw.arc([u(40), u(26), u(50), u(46)], start=180, end=360, fill=(176, 158, 132, 255), width=int(u(2.5)))
    draw.arc([u(50), u(26), u(60), u(46)], start=180, end=360, fill=(176, 158, 132, 255), width=int(u(2.5)))
    # interior pocket line
    rr(draw, 38, 50, 62, 72, 2, outline=(176, 158, 132, 255), width=int(u(1.2)), fill=None)
    # brand mark
    draw.rounded_rectangle([u(46), u(62), u(54), u(66)], radius=u(1), fill=(120, 116, 108, 255))


def draw_backpack(draw):
    # main body
    rr(draw, 36, 30, 64, 78, 8, fill=LILAC, outline=(170, 150, 176, 255), width=2)
    # top handle
    draw.arc([u(44), u(22), u(56), u(34)], start=180, end=360, fill=(170, 150, 176, 255), width=int(u(2.5)))
    # front pocket
    rr(draw, 40, 44, 60, 66, 5, fill=(200, 186, 206, 255), outline=(170, 150, 176, 255), width=2)
    # zipper
    draw.line([u(40), u(52), u(60), u(52)], fill=(150, 132, 158, 255), width=int(u(1.5)))
    # straps
    rr(draw, 38, 30, 42, 40, 2, fill=(170, 150, 176, 255))
    rr(draw, 58, 30, 62, 40, 2, fill=(170, 150, 176, 255))
    # pocket zipper pull
    draw.line([u(60), u(52), u(62), u(56)], fill=(150, 132, 158, 255), width=int(u(1.5)))


def draw_bottle(draw):
    # body
    rr(draw, 42, 36, 58, 78, 5, fill=STONE, outline=(120, 116, 108, 255), width=2)
    # shoulder
    rr(draw, 44, 28, 56, 40, 3, fill=STONE, outline=(120, 116, 108, 255), width=2)
    # cap
    rr(draw, 45, 20, 55, 30, 2, fill=INK, outline=INK, width=2)
    # loop
    draw.arc([u(51), u(16), u(61), u(26)], start=0, end=180, fill=(120, 116, 108, 255), width=int(u(2)))
    # highlight
    rr(draw, 46, 42, 49, 74, 2, fill=(240, 236, 228, 255))
    # label band
    rr(draw, 43, 52, 57, 64, 1, fill=(232, 223, 208, 255), outline=(120, 116, 108, 255), width=1)


def draw_notebook(draw):
    # cover (slightly open)
    rr(draw, 28, 26, 72, 76, 4, fill=PERIWINKLE, outline=(150, 162, 190, 255), width=2)
    # pages
    rr(draw, 30, 28, 70, 74, 2, fill=WHITE, outline=(210, 205, 196, 255), width=1)
    # spine
    rr(draw, 26, 26, 30, 76, 2, fill=(120, 116, 108, 255))
    # ruled lines
    for y in range(38, 72, 6):
        draw.line([u(34), u(y), u(66), u(y)], fill=(214, 210, 200, 255), width=int(u(0.8)))
    # elastic band
    draw.line([u(28), u(60), u(72), u(50)], fill=(150, 162, 190, 255), width=int(u(1.5)))


def draw_pens(draw):
    # canvas case
    rr(draw, 28, 52, 72, 76, 6, fill=SAND, outline=(176, 158, 132, 255), width=2)
    # zipper
    draw.line([u(28), u(58), u(72), u(58)], fill=(120, 116, 108, 255), width=int(u(1.5)))
    # pen 1
    rr(draw, 34, 40, 66, 46, 3, fill=INK, width=0)
    rr(draw, 34, 44, 66, 50, 3, fill=(52, 58, 68, 255))
    draw.ellipse([u(64), u(41), u(68), u(49)], fill=(52, 58, 68, 255))
    # pen 2
    rr(draw, 36, 30, 68, 36, 3, fill=NAVY, width=0)
    rr(draw, 36, 34, 68, 40, 3, fill=(60, 68, 84, 255))
    draw.ellipse([u(66), u(31), u(70), u(39)], fill=(60, 68, 84, 255))
    # clip on pen 2
    draw.line([u(40), u(30), u(40), u(36)], fill=(140, 146, 158, 255), width=int(u(1.5)))


PRODUCT_DRAWERS = {
    "URUMI-TEE-001": draw_tee,
    "URUMI-HOODIE-001": draw_hoodie,
    "102938": draw_shoes,
    "URUMI-CAP-001": draw_cap,
    "URUMI-MUG-001": draw_mug,
    "URUMI-CANDLE-001": draw_candle,
    "URUMI-THROW-001": draw_throw,
    "URUMI-TOTE-001": draw_tote,
    "URUMI-BACKPACK-001": draw_backpack,
    "URUMI-BOTTLE-001": draw_bottle,
    "URUMI-NOTEBOOK-001": draw_notebook,
    "URUMI-PEN-001": draw_pens,
}


def render_product(sku: str, transparent: bool) -> Image.Image:
    """Render the product artwork at SIZE x SIZE (transparent or on a tile bg)."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0) if transparent else (*TILE_BG, 255))
    draw = ImageDraw.Draw(img)
    drawer = PRODUCT_DRAWERS.get(sku)
    if drawer:
        drawer(draw)
    if not transparent:
        soft_shadow(draw, 50, 72, 16, 6, alpha=40)
        overlay_light(draw)
    return img


def main() -> int:
    with open(PRODUCTS_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    os.makedirs(OUT_DIR, exist_ok=True)
    total_tiles = 0
    total_cutouts = 0
    print(f"Generating images for {len(data['products'])} products -> {OUT_DIR}")
    for p in data["products"]:
        sku = p["sku"]
        image_name = p.get("image") or f"{sku}.png"
        cutout_name = image_name.replace(".png", "-cutout.png")
        tile_path = os.path.join(OUT_DIR, image_name)
        cutout_path = os.path.join(OUT_DIR, cutout_name)

        if os.path.exists(tile_path) and not FORCE:
            print(f"  keep   {image_name} (already exists; drop in a better photo to replace)")
        else:
            render_product(sku, transparent=False).save(tile_path, "PNG", optimize=True)
            print(f"  wrote  {image_name}")
        total_tiles += 1

        if os.path.exists(cutout_path) and not FORCE:
            print(f"  keep   {cutout_name} (already exists)")
        else:
            render_product(sku, transparent=True).save(cutout_path, "PNG", optimize=True)
            print(f"  wrote  {cutout_name}")
        total_cutouts += 1

    print(f"\nRendered {total_tiles} tiles + {total_cutouts} cutouts.")
    print("Sizes:")
    for name in sorted(os.listdir(OUT_DIR)):
        if not name.endswith(".png"):
            continue
        size_kb = os.path.getsize(os.path.join(OUT_DIR, name)) / 1024
        flag = "OK" if (name.endswith("-cutout.png") and size_kb < 250) or (not name.endswith("-cutout.png") and size_kb < 150) else "OVER"
        print(f"  {name:42s} {size_kb:8.1f} KB  {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
