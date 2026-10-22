#!/usr/bin/env python3
"""Generate ORIGINAL illustrated product images for the Loam & Ember store.

Reads store/products.json and renders, for every product SKU:
  <sku>.png          main tile, 1000x1000, flat illustration on a soft tile bg
  <sku>-2.png        gallery: same product, alternate composition + tint wash
  <sku>-3.png        gallery: detail crop (zoomed into the artwork)
  <sku>-4.png        gallery: context scene (featured/new products only)
  <sku>-cutout.png   transparent cutout for the hero and category tiles

All artwork is original flat illustration drawn with Pillow: no third-party
assets, no photos, no copyrighted likenesses, no people. Files respect the
store budgets (<=1000 px longest side, small KB, whole catalog well under the
12 MB cap). Existing files are never regenerated unless --force is passed, so
hand-dropped replacements with the same name survive.

Run:  /path/to/python-with-PIL scripts/gen-store-images.py [--force]
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCTS_JSON = os.path.join(ROOT, "store", "products.json")
OUT_DIR = os.path.join(ROOT, "store", "images")

SIZE = 1000
UNIT = SIZE / 100.0
FORCE = "--force" in sys.argv

# Token family (see docs/STORE_DESIGN.md). These drive the artwork only.
TILE_BG = (243, 242, 239)        # tile #F3F2EF
INK = (20, 23, 28)               # ink #14171C
WHITE = (250, 250, 250)
CREAM = (244, 241, 234)
STONE = (208, 202, 192)
CHARCOAL = (82, 88, 98)

TINTS = {
    "periwinkle": ((185, 196, 221), (142, 158, 194)),
    "lilac":      ((217, 200, 220), (176, 152, 181)),
    "peach":      ((239, 203, 190), (213, 160, 141)),
    "sand":       ((232, 223, 208), (196, 178, 148)),
    "sage":       ((216, 224, 212), (163, 181, 160)),
    "clay":       ((235, 217, 204), (201, 161, 137)),
}


def u(v):
    return v * UNIT


def soft_shadow(draw: ImageDraw.ImageDraw, cx, cy, rx, ry, alpha=46) -> None:
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(20, 23, 28, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=u(1.5)))
    draw._image.alpha_composite(layer)


def overlay_light(draw: ImageDraw.ImageDraw) -> None:
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.polygon([u(0), u(0), u(100), u(0), u(0), u(100)], fill=(255, 255, 255, 10))
    draw._image.alpha_composite(layer)


def vignette(draw: ImageDraw.ImageDraw, strength=14) -> None:
    """Soft corner darkening for a printed-paper feel; few bands, compresses fine."""
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rectangle([0, 0, SIZE, SIZE], fill=(20, 23, 28, 0))
    ld.rectangle([0, 0, SIZE, SIZE], outline=(20, 23, 28, strength), width=int(u(7)))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=u(4)))
    draw._image.alpha_composite(layer)


def rr(draw, x0, y0, x1, y1, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle([u(x0), u(y0), u(x1), u(y1)], radius=u(radius),
                           fill=fill, outline=outline, width=max(1, int(u(width))))


def speckle(draw, x0, y0, x1, y1, color, n=26, seed=7):
    import random
    rnd = random.Random(seed)
    for _ in range(n):
        x = rnd.uniform(x0 + 2, x1 - 2)
        y = rnd.uniform(y0 + 2, y1 - 2)
        draw.ellipse([u(x), u(y), u(x + 0.9), u(y + 0.9)], fill=color)


def weave(draw, x0, y0, x1, y1, color, step=3):
    y = y0 + step / 2
    while y < y1:
        draw.line([u(x0), u(y), u(x1), u(y)], fill=color, width=max(1, int(u(0.8))))
        y += step


# ---------------------------------------------------------------- shape kinds

def vessel(draw, tint, motif, *, w=30, h=40, handle=False, lid=False, neck=0, spout=False, pump=False):
    body, edge = TINTS[tint]
    x0, x1 = 50 - w / 2, 50 + w / 2
    y0, y1 = 74 - h, 74
    if neck:
        rr(draw, 50 - neck / 2, y0 - 8, 50 + neck / 2, y0 + 6, 2, fill=body, outline=edge, width=1.6)
    rr(draw, x0, y0, x1, y1, 6, fill=body, outline=edge, width=1.6)
    if motif == "speckle":
        speckle(draw, x0 + 2, y0 + 2, x1 - 2, y1 - 2, (250, 250, 250, 160))
    if motif == "label":
        rr(draw, x0 + 5, 50, x1 - 5, 64, 2, fill=CREAM, outline=edge, width=1)
        draw.line([u(x0 + 9), u(55), u(x1 - 9), u(55)], fill=edge, width=max(1, int(u(0.9))))
        draw.line([u(x0 + 9), u(59), u(x1 - 13), u(59)], fill=edge, width=max(1, int(u(0.7))))
    rr(draw, x0 + 2.5, y0 + 2, x0 + 5, y1 - 3, 2, fill=(255, 255, 255, 90))
    if handle:
        draw.arc([u(x1 - 2), u(y0 + h * 0.25), u(x1 + 12), u(y0 + h * 0.75)],
                 start=-90, end=90, fill=edge, width=max(1, int(u(2.6))))
    if spout:
        draw.polygon([u(x0 + 1), u(y0 + 6), u(x0 - 8), u(y0 - 2), u(x0 + 1), u(y0 + 12)], fill=body, outline=edge)
    if lid:
        rr(draw, x0 - 2, y0 - 4, x1 + 2, y0 + 2, 2, fill=(120, 116, 108, 255), outline=(100, 96, 88, 255), width=1.2)
        draw.line([u(50), u(y0 - 4), u(50), u(y0 - 8)], fill=(100, 96, 88, 255), width=max(1, int(u(1.2))))
    if pump:
        rr(draw, 47, y0 - 10, 53, y0 + 1, 1.5, fill=INK, outline=INK, width=0.8)
        rr(draw, 50, y0 - 14, 58, y0 - 9, 1.5, fill=INK, outline=INK, width=0.8)


def bowl(draw, tint, motif):
    body, edge = TINTS[tint]
    draw.polygon([u(26), u(52), u(74), u(52), u(66), u(74), u(34), u(74)], fill=body, outline=edge)
    draw.ellipse([u(24), u(46), u(76), u(58)], fill=(250, 250, 250, 255), outline=edge, width=max(1, int(u(1.4))))
    draw.ellipse([u(28), u(48), u(72), u(56)], fill=body)
    if motif == "speckle":
        speckle(draw, 32, 58, 68, 72, (250, 250, 250, 160), seed=11)
    draw.ellipse([u(33), u(74), u(67), u(78)], fill=(20, 23, 28, 0))


def plates(draw, tint, motif):
    body, edge = TINTS[tint]
    for i, (dx, dy) in enumerate([(0, 8), (3, 4), (6, 0)]):
        draw.ellipse([u(24 + dx), u(40 + dy), u(76 + dx), u(66 + dy)], fill=body, outline=edge,
                     width=max(1, int(u(1.4))))
    draw.ellipse([u(32 + 6), u(47), u(68 + 6), u(61)], fill=(250, 250, 250, 255), outline=edge,
                 width=max(1, int(u(1))))
    if motif == "speckle":
        speckle(draw, 34, 50, 70, 60, (250, 250, 250, 170), seed=5)


def textiles(draw, tint, motif, *, wide=False):
    body, edge = TINTS[tint]
    x0, x1 = (22, 78) if wide else (28, 72)
    y = 40
    for i, shade in enumerate((body, tuple(min(255, c + 12) for c in body), body)):
        rr(draw, x0 + i * 1.5, y, x1 - i * 1.5, y + 9, 3, fill=shade, outline=edge, width=1.2)
        y += 8
    if motif == "stripe":
        for sx in range(int(x0) + 6, int(x1) - 4, 8):
            draw.line([u(sx), u(42), u(sx), u(62)], fill=(255, 255, 255, 150), width=max(1, int(u(1.4))))
    if motif == "waffle":
        for wy in range(43, 62, 4):
            draw.line([u(x0 + 3), u(wy), u(x1 - 3), u(wy)], fill=(255, 255, 255, 120),
                      width=max(1, int(u(0.8))))
    if motif == "fringe":
        for i in range(9):
            fx = x0 + 3 + i * (x1 - x0 - 6) / 8
            draw.line([u(fx), u(64), u(fx), u(70)], fill=edge, width=max(1, int(u(1.1))))


def cushion(draw, tint, motif):
    body, edge = TINTS[tint]
    rr(draw, 26, 34, 74, 74, 8, fill=body, outline=edge, width=1.6)
    rr(draw, 30, 38, 70, 70, 6, fill=tuple(min(255, c + 10) for c in body), outline=edge, width=1)
    draw.line([u(50), u(38), u(50), u(44)], fill=edge, width=max(1, int(u(1))))
    rr(draw, 47.6, 40, 52.4, 68, 1, fill=(255, 255, 255, 60))


def boxish(draw, tint, motif, *, w=40, h=28, r=3):
    body, edge = TINTS[tint]
    x0, x1 = 50 - w / 2, 50 + w / 2
    y0, y1 = 62 - h, 62
    rr(draw, x0, y0, x1, y1, r, fill=body, outline=edge, width=1.6)
    if motif == "elastic":
        draw.line([u(x0), u(y0 + h * 0.62), u(x1), u(y0 + h * 0.38)], fill=edge, width=max(1, int(u(1.4))))
        rr(draw, x0 + 4, y0 + 5, x0 + 10, y0 + h - 5, 1.5, fill=(255, 255, 255, 80))
    if motif == "zip":
        draw.line([u(x0 + 2), u(y0 + 4), u(x1 - 2), u(y0 + 4)], fill=(120, 116, 108, 255),
                  width=max(1, int(u(1.2))))
        draw.line([u(x1 - 6), u(y0 + 4), u(x1 - 6), u(y0 + 8)], fill=(120, 116, 108, 255),
                  width=max(1, int(u(1.2))))
    if motif == "label":
        rr(draw, 44, 48, 56, 56, 1.5, fill=CREAM, outline=edge, width=0.8)
    if motif == "weave":
        weave(draw, x0 + 2, y0 + 3, x1 - 2, y1 - 2, (255, 255, 255, 110), step=3.2)


def bag(draw, tint, motif, *, kind="tote"):
    body, edge = TINTS[tint]
    if kind == "tote":
        rr(draw, 30, 40, 70, 78, 4, fill=body, outline=edge, width=1.6)
        draw.arc([u(38), u(26), u(50), u(46)], start=180, end=360, fill=edge, width=max(1, int(u(2.4))))
        draw.arc([u(50), u(26), u(62), u(46)], start=180, end=360, fill=edge, width=max(1, int(u(2.4))))
        rr(draw, 38, 50, 62, 72, 2, outline=edge, width=1)
        rr(draw, 42, 56, 58, 64, 1.5, fill=(255, 255, 255, 70))
    elif kind == "duffel":
        rr(draw, 26, 42, 74, 72, 12, fill=body, outline=edge, width=1.6)
        draw.arc([u(42), u(30), u(58), u(46)], start=180, end=360, fill=edge, width=max(1, int(u(2.4))))
        draw.line([u(26), u(50), u(74), u(50)], fill=edge, width=max(1, int(u(1))))
        rr(draw, 40, 54, 60, 58, 1.5, fill=(255, 255, 255, 70))
    elif kind == "sack":
        draw.polygon([u(34), u(40), u(66), u(40), u(70), u(78), u(30), u(78)], fill=body, outline=edge)
        draw.line([u(40), u(38), u(52), u(30)], fill=edge, width=max(1, int(u(1.8))))
        draw.line([u(60), u(38), u(52), u(30)], fill=edge, width=max(1, int(u(1.8))))
        rr(draw, 44, 62, 56, 66, 1.5, fill=(255, 255, 255, 70))
    elif kind == "basket":
        draw.polygon([u(30), u(44), u(70), u(44), u(64), u(76), u(36), u(76)], fill=body, outline=edge)
        weave(draw, 31, 46, 69, 76, (255, 255, 255, 120), step=3)
        draw.arc([u(36), u(34), u(64), u(50)], start=180, end=360, fill=edge, width=max(1, int(u(2.2))))
    elif kind == "sleeve":
        rr(draw, 24, 42, 76, 70, 6, fill=body, outline=edge, width=1.6)
        draw.line([u(24), u(48), u(76), u(48)], fill=(120, 116, 108, 255), width=max(1, int(u(1.2))))
        rr(draw, 46, 46, 54, 50, 1, fill=(120, 116, 108, 255))
    elif kind == "apron":
        draw.polygon([u(38), u(34), u(62), u(34), u(68), u(78), u(32), u(78)], fill=body, outline=edge)
        draw.arc([u(42), u(24), u(58), u(40)], start=180, end=360, fill=edge, width=max(1, int(u(1.8))))
        rr(draw, 42, 52, 58, 64, 2, outline=edge, width=1)


def candle(draw, tint, motif):
    body, edge = TINTS[tint]
    rr(draw, 34, 34, 66, 78, 5, fill=STONE, outline=(160, 154, 144, 255), width=1.6)
    rr(draw, 36, 40, 64, 76, 4, fill=(244, 233, 214, 255))
    if motif == "label-alt":
        rr(draw, 40, 50, 60, 66, 2, fill=(216, 224, 212, 255), outline=(163, 181, 160, 255), width=1)
    else:
        rr(draw, 40, 50, 60, 66, 2, fill=CREAM, outline=(176, 158, 132, 255), width=1)
    draw.line([u(44), u(56), u(56), u(56)], fill=(120, 116, 108, 255), width=max(1, int(u(0.9))))
    draw.line([u(44), u(60), u(52), u(60)], fill=(120, 116, 108, 255), width=max(1, int(u(0.7))))
    draw.line([u(50), u(34), u(50), u(40)], fill=(70, 64, 58, 255), width=max(1, int(u(1.3))))
    rr(draw, 31, 27, 69, 36, 3, fill=(160, 152, 140, 255), outline=(140, 132, 122, 255), width=1.2)


def melts(draw, tint, motif):
    body, edge = TINTS[tint]
    rr(draw, 28, 46, 72, 70, 4, fill=(250, 250, 250, 255), outline=(200, 196, 188, 255), width=1.4)
    for i, cx in enumerate((36, 46, 56, 66)):
        draw.rounded_rectangle([u(cx - 4), u(52), u(cx + 4), u(64)], radius=u(1.5),
                               fill=body, outline=edge, width=1)
    draw.line([u(28), u(52), u(72), u(52)], fill=(200, 196, 188, 255), width=max(1, int(u(0.8))))


def soap(draw, tint, motif):
    body, edge = TINTS[tint]
    rr(draw, 30, 48, 70, 70, 6, fill=body, outline=edge, width=1.6)
    draw.ellipse([u(44), u(53), u(56), u(63)], outline=edge, width=max(1, int(u(1))))
    draw.line([u(47), u(58), u(53), u(58)], fill=edge, width=max(1, int(u(0.9))))
    draw.line([u(50), u(55), u(50), u(61)], fill=edge, width=max(1, int(u(0.9))))


def incense(draw, tint, motif):
    body, edge = TINTS[tint]
    draw.chord([u(30), u(52), u(70), u(84)], start=180, end=360, fill=body, outline=edge,
               width=max(1, int(u(1.6))))
    draw.ellipse([u(30), u(66), u(70), u(76)], fill=tuple(min(255, c + 8) for c in body),
                 outline=edge, width=max(1, int(u(1))))
    draw.line([u(50), u(34), u(66), u(66)], fill=(120, 116, 108, 255), width=max(1, int(u(1.2))))
    import math
    pts = []
    for t in range(0, 30):
        x = 48 - t * 0.18
        y = 34 - t * 0.5 + math.sin(t / 3) * 0.8
        pts.append((u(x), u(y)))
    draw.line(pts, fill=(190, 186, 178, 200), width=max(1, int(u(1))))


def letters(draw, tint, motif):
    body, edge = TINTS[tint]
    rr(draw, 30, 40, 70, 72, 2, fill=CREAM, outline=(196, 178, 148, 255), width=1.4)
    draw.polygon([u(30), u(40), u(50), u(58), u(70), u(40)], fill=(236, 228, 212, 255),
                 outline=(196, 178, 148, 255))
    rr(draw, 36, 62, 64, 70, 1.5, fill=body, outline=edge, width=1)


def planner(draw, tint, motif):
    body, edge = TINTS[tint]
    rr(draw, 26, 36, 74, 72, 2, fill=WHITE, outline=(206, 200, 190, 255), width=1.4)
    rr(draw, 26, 32, 74, 38, 1.5, fill=body, outline=edge, width=1)
    for gy in range(46, 68, 7):
        draw.line([u(31), u(gy), u(69), u(gy)], fill=(214, 210, 200, 255), width=max(1, int(u(0.8))))
    draw.line([u(31), u(41), u(69), u(41)], fill=edge, width=max(1, int(u(0.9))))


def tray(draw, tint, motif):
    body, edge = TINTS[tint]
    rr(draw, 24, 42, 76, 70, 4, fill=body, outline=edge, width=1.6)
    rr(draw, 28, 47, 72, 65, 2, fill=tuple(min(255, c + 10) for c in body), outline=edge, width=1)
    rr(draw, 33, 55, 43, 61, 1.5, fill=(255, 255, 255, 80))
    draw.ellipse([u(52), u(54), u(62), u(62)], fill=WHITE, outline=edge, width=1)


def board(draw, tint, motif):
    body, edge = TINTS[tint]
    rr(draw, 32, 36, 68, 78, 4, fill=(150, 118, 94, 255), outline=(122, 94, 74, 255), width=1.6)
    rr(draw, 36, 40, 64, 76, 3, fill=(216, 224, 212, 255), outline=(163, 181, 160, 255), width=1)
    draw.ellipse([u(46), u(40), u(54), u(46)], fill=(122, 94, 74, 255))
    draw.line([u(38), u(52), u(62), u(52)], fill=(122, 94, 74, 160), width=max(1, int(u(0.8))))
    draw.line([u(38), u(58), u(62), u(58)], fill=(122, 94, 74, 160), width=max(1, int(u(0.8))))


def trivet(draw, tint, motif):
    body, edge = TINTS[tint]
    rr(draw, 30, 44, 70, 74, 3, fill=body, outline=edge, width=1.6)
    speckle(draw, 32, 46, 68, 72, (250, 250, 250, 170), seed=3)
    for cx, cy in ((34, 71), (66, 71), (34, 47), (66, 47)):
        draw.ellipse([u(cx - 1.6), u(cy - 1.2), u(cx + 1.6), u(cy + 1.2)], fill=(150, 130, 100, 255))


def spoons(draw, tint, motif):
    body, edge = TINTS[tint]
    draw.line([u(30), u(40), u(70), u(40)], fill=(120, 116, 108, 255), width=max(1, int(u(1.6))))
    for i, cx in enumerate((36, 46, 56, 66)):
        draw.line([u(cx), u(40), u(cx), u(48)], fill=(140, 146, 158, 255), width=max(1, int(u(1))))
        draw.ellipse([u(cx - 2.4), u(48), u(cx + 2.4), u(58)], fill=STONE, outline=(120, 116, 108, 255),
                     width=max(1, int(u(1))))
        draw.line([u(cx), u(58), u(cx), u(72)], fill=STONE, width=max(1, int(u(1.4))))
        draw.ellipse([u(cx - 1), u(72), u(cx + 1), u(74)], fill=STONE)


def pens(draw, tint, motif):
    body, edge = TINTS[tint]
    rr(draw, 28, 56, 72, 76, 5, fill=body, outline=edge, width=1.6)
    draw.line([u(28), u(62), u(72), u(62)], fill=(120, 116, 108, 255), width=max(1, int(u(1.2))))
    rr(draw, 34, 46, 66, 51, 2, fill=INK, width=0)
    draw.ellipse([u(64), u(46.5), u(68), u(50.5)], fill=(52, 58, 68, 255))
    rr(draw, 36, 38, 68, 43, 2, fill=(72, 80, 96, 255), width=0)
    draw.ellipse([u(66), u(38.5), u(70), u(42.5)], fill=(60, 68, 84, 255))


KINDS = {
    "mug":       lambda d, t, m: vessel(d, t, m, w=30, h=38, handle=True),
    "bowl":      lambda d, t, m: bowl(d, t, m),
    "plates":    lambda d, t, m: plates(d, t, m),
    "vase":      lambda d, t, m: vessel(d, t, m, w=18, h=40, neck=10),
    "teapot":    lambda d, t, m: vessel(d, t, m, w=36, h=32, spout=True, lid=True, handle=True),
    "spoonrest": lambda d, t, m: bowl(d, t, m),
    "throw":     lambda d, t, m: textiles(d, t, m, wide=True),
    "cushion":   lambda d, t, m: cushion(d, t, m),
    "napkins":   lambda d, t, m: textiles(d, t, m),
    "towels":    lambda d, t, m: textiles(d, t, m, wide=True),
    "runner":    lambda d, t, m: textiles(d, t, m, wide=True),
    "bathmat":   lambda d, t, m: textiles(d, t, m, wide=True),
    "candle":    lambda d, t, m: candle(d, t, m),
    "melts":     lambda d, t, m: melts(d, t, m),
    "soap":      lambda d, t, m: soap(d, t, m),
    "mist":      lambda d, t, m: vessel(d, t, m, w=20, h=44, neck=8, pump=True),
    "incense":   lambda d, t, m: incense(d, t, m),
    "notebook":  lambda d, t, m: boxish(d, t, m, w=42, h=32, r=3),
    "pens":      lambda d, t, m: pens(d, t, m),
    "pouch":     lambda d, t, m: boxish(d, t, m, w=38, h=22, r=5),
    "tray":      lambda d, t, m: tray(d, t, m),
    "planner":   lambda d, t, m: planner(d, t, m),
    "letters":   lambda d, t, m: letters(d, t, m),
    "board":     lambda d, t, m: board(d, t, m),
    "jar":       lambda d, t, m: vessel(d, t, m, w=26, h=36, lid=True),
    "trivet":    lambda d, t, m: trivet(d, t, m),
    "apron":     lambda d, t, m: bag(d, t, m, kind="apron"),
    "spoons":    lambda d, t, m: spoons(d, t, m),
    "tote":      lambda d, t, m: bag(d, t, m, kind="tote"),
    "duffel":    lambda d, t, m: bag(d, t, m, kind="duffel"),
    "sack":      lambda d, t, m: bag(d, t, m, kind="sack"),
    "basket":    lambda d, t, m: bag(d, t, m, kind="basket"),
    "sleeve":    lambda d, t, m: bag(d, t, m, kind="sleeve"),
}


def render_product(p: dict, transparent: bool, bg=(TILE_BG)) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0) if transparent else (*bg, 255))
    draw = ImageDraw.Draw(img)
    drawer = KINDS.get(p.get("kind", "boxish"))
    if drawer:
        drawer(draw, p.get("tint", "sand"), p.get("motif", "none"))
    if not transparent:
        soft_shadow(draw, 50, 80, 17, 5.5, alpha=38)
        overlay_light(draw)
        vignette(draw)
    return img


def alt_bg(p: dict):
    """Gallery -2: a slightly warmer/cooler wash than the main tile."""
    base = TINTS.get(p.get("tint", "sand"), ((232, 223, 208), None))[0]
    mix = tuple((c * 3 + b * 1) // 4 for c, b in zip(base, (250, 250, 250)))
    # soften: blend further toward cream
    return tuple((c + 244) // 2 for c in mix)


def main() -> int:
    with open(PRODUCTS_JSON, encoding="utf-8") as fh:
        data = json.load(fh)
    os.makedirs(OUT_DIR, exist_ok=True)
    n = 0
    print(f"Generating images for {len(data['products'])} products -> {OUT_DIR}")

    def maybe(path: str, fn):
        nonlocal n
        if os.path.exists(path) and not FORCE:
            return
        fn()
        n += 1

    for p in data["products"]:
        sku = p["sku"]
        main_img = os.path.join(OUT_DIR, p.get("image", f"{sku}.png"))
        cutout = os.path.join(OUT_DIR, f"{sku}-cutout.png")

        def do_main():
            render_product(p, transparent=False).save(main_img, "PNG", optimize=True)
        def do_cutout():
            render_product(p, transparent=True).save(cutout, "PNG", optimize=True)
        maybe(main_img, do_main)
        maybe(cutout, do_cutout)

        # gallery -2: alternate tinted bg, slightly offset composition
        alt = os.path.join(OUT_DIR, f"{sku}-2.png")

        def do_alt():
            bgc = alt_bg(p)
            img = render_product(p, transparent=False, bg=bgc)
            # small offset: shift the artwork down-left by re-compositing
            shifted = Image.new("RGBA", (SIZE, SIZE), (*bgc, 255))
            art = render_product(p, transparent=True)
            art = art.transform(art.size, Image.AFFINE, (1, 0, -40, 0, 1, 30))
            shifted.alpha_composite(art)
            soft_shadow(ImageDraw.Draw(shifted), 48, 82, 17, 5.5, alpha=30)
            overlay_light(ImageDraw.Draw(shifted))
            shifted.save(alt, "PNG", optimize=True)
        maybe(alt, do_alt)

        # gallery -3: detail crop (zoom into the upper-middle region)
        det = os.path.join(OUT_DIR, f"{sku}-3.png")

        def do_det():
            art = render_product(p, transparent=False)
            crop = art.crop((int(u(30)), int(u(34)), int(u(76)), int(u(72))))
            crop = crop.resize((SIZE, SIZE), Image.LANCZOS)
            crop = crop.filter(ImageFilter.GaussianBlur(radius=0.6))
            crop = crop.convert('RGB').quantize(colors=192, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG)
            crop.save(det, "PNG", optimize=True)
        maybe(det, do_det)

        # gallery -4: context scene (product on a table line with a second faint object)
        if len(p.get("gallery", [])) >= 3:
            ctx4 = os.path.join(OUT_DIR, f"{sku}-4.png")

            def do_ctx():
                bgc = CREAM
                img = Image.new("RGBA", (SIZE, SIZE), (*bgc, 255))
                draw = ImageDraw.Draw(img)
                # table edge + wall shadow for a scene feel
                draw.rectangle([0, int(u(78)), SIZE, SIZE], fill=(232, 228, 220, 255))
                draw.line([0, int(u(78)), SIZE, int(u(78))], fill=(206, 200, 190, 255), width=int(u(0.8)))
                art = render_product(p, transparent=True).transform(
                    Image.Size(SIZE, SIZE) if False else art_size(), Image.AFFINE, (0.8, 0, 100, 0, 0.8, 200))
                img.alpha_composite(art)
                # faint companion object (a simple vessel silhouette)
                sil = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
                sd = ImageDraw.Draw(sil)
                sd.rounded_rectangle([u(16), u(56), u(30), u(78)], radius=u(3), fill=(206, 200, 190, 255))
                sil = sil.filter(ImageFilter.GaussianBlur(1.2))
                img.alpha_composite(sil)
                soft_shadow(draw, 55, 88, 15, 4, alpha=28)
                overlay_light(draw)
                img.save(ctx4, "PNG", optimize=True)
            maybe(ctx4, do_ctx)

    print(f"Rendered/kept files total writes: {n}")
    total = 0
    over = []
    for name in sorted(os.listdir(OUT_DIR)):
        if not name.endswith(".png"):
            continue
        kb = os.path.getsize(os.path.join(OUT_DIR, name)) / 1024
        total += kb
        if kb > 120:
            over.append((name, kb))
    with Image.open(os.path.join(OUT_DIR, data["products"][0]["image"])) as im:
        print(f"longest side: {max(im.size)} px")
    print(f"total: {total/1024:.1f} MB across {len(os.listdir(OUT_DIR))} files")
    if over:
        print("OVER 120KB:", over)
    return 0


def art_size():
    return (SIZE, SIZE)


if __name__ == "__main__":
    raise SystemExit(main())
