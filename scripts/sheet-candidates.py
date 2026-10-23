#!/usr/bin/env python3
"""Build candidate review sheets: one sheet per cached search, all previews in a
grid with index numbers. Pure curation aid; never committed to runtime assets."""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "artifacts" / "store-photos" / "cache"
OUT = ROOT / "artifacts" / "store-photos" / "sheets"
OUT.mkdir(parents=True, exist_ok=True)

CELL_W, CELL_H, PAD, LABEL_H = 300, 375, 8, 26


def sheet(name: str) -> None:
    data = json.loads((CACHE / f"search-{name}.json").read_text())
    prev_dir = CACHE / "previews" / name
    files = sorted(p for p in prev_dir.glob("*.jpg"))
    if not files:
        sys.exit(f"no previews for {name}")
    per = 6
    rows = (len(files) + per - 1) // per
    W = per * (CELL_W + PAD) + PAD
    H = rows * (CELL_H + LABEL_H + PAD) + PAD
    canvas = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(canvas)
    for k, f in enumerate(files):
        idx = int(f.stem)
        col, row = k % per, k // per
        x = PAD + col * (CELL_W + PAD)
        y = PAD + row * (CELL_H + LABEL_H + PAD)
        im = Image.open(f).convert("RGB")
        im.thumbnail((CELL_W, CELL_H))
        canvas.paste(im, (x + (CELL_W - im.width) // 2, y))
        ph = next((p for p in data["results"] if p["i"] == idx), None)
        label = f"[{idx:02d}] {ph['desc'][:34] if ph else ''}"
        d.text((x, y + CELL_H + 4), label, fill="#000000")
    dest = OUT / f"sheet-{name}.jpg"
    canvas.save(dest, quality=72)
    print(f"{dest}  ({len(files)} candidates, {canvas.width}x{canvas.height})")


if __name__ == "__main__":
    for nm in sys.argv[1:]:
        sheet(nm)
