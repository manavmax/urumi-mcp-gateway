#!/usr/bin/env python3
"""Photo processing pipeline for the Loam & Ember store (photo-first pass).

Runs AFTER photo curation. Input: artifacts/store-photos/choices.json
(gitignored), written during curation:

{
  "hero":      {"search": "lifestyle", "index": 3, "verdict": "..."},
  "editorial": {"search": "lifestyle", "index": 7},
  "products": [
    {"sku": "LOAM-CER-001", "search": "ceramics-vase", "index": 11,
     "name": "Stoneware Vase", "verdict": "speckled stoneware vase on oak",
     "gallery": "crop"},
    ...
  ]
}

"gallery" is one of:
  "crop"                     -> <SKU>-2.webp is a centre detail crop (1.6x zoom)
                                of the same photograph
  "photo:<search>:<index>"   -> a second distinct real photo
  "none"                     -> no gallery image

Per product the pipeline:
  1. downloads the chosen photo (download_location ping + raw w=1600, cached)
  2. center-crops to 4:5 and resizes to 960x1200 (long side 1200)
  3. encodes webp at q80 down to q60 until the file is <= 150KB
  4. writes store/images/<SKU>.webp and, when used, <SKU>-2.webp
  5. writes artifacts/store-photos/manifest.json and docs/IMAGE_CREDITS.md
  6. builds artifacts/store-photos/contact-sheet.png (photos + names + SKUs)

The hero gets a separate full-bleed wide crop (bounded by the w=1600 source,
about 1600x720) written as hero.webp; the catalog "hero" entry references it.
The 600px variant is not a second shipped file: the theme registers the
urumi-600 image size so WordPress derives a 480x600 copy from each sideloaded
1200px master and serves both via srcset.

Safety: the Unsplash Access Key is read only inside this script's api_get()
and never printed or logged. Nothing here runs at store runtime.
"""
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "artifacts" / "store-photos" / "cache"
GRABS = CACHE / "grabs-full"
IMAGES = ROOT / "store" / "images"
CHOICES = ROOT / "artifacts" / "store-photos" / "choices.json"
MANIFEST_OUT = ROOT / "artifacts" / "store-photos" / "manifest.json"
CREDITS = ROOT / "docs" / "IMAGE_CREDITS.md"
CONTACT = ROOT / "artifacts" / "store-photos" / "contact-sheet.png"

LONG_W, LONG_H = 960, 1200        # 4:5 grid master, long side 1200
MAX_BYTES = 150_000
HERO_W, HERO_H = 2000, 900        # hero target; output width is source-bounded
HERO_MAX = 250_000


def api_get(url: str):
    """GET with the Unsplash key header. The key is read here, never printed."""
    key = (ROOT / ".unsplash_key").read_text(encoding="utf-8").strip()
    req = urllib.request.Request(url, headers={"Authorization": f"Client-ID {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = r.read()
    if url.startswith("https://api.unsplash.com"):
        return json.loads(payload.decode())
    return payload


def grab_full(name: str, idx: int) -> tuple[Path, dict]:
    """Download one chosen photo at w=1600, tracking the download once."""
    GRABS.mkdir(parents=True, exist_ok=True)
    (CACHE / "grabbed").mkdir(parents=True, exist_ok=True)
    data = json.loads((CACHE / f"search-{name}.json").read_text())
    ph = next(p for p in data["results"] if p["i"] == idx)
    dest = GRABS / f"{ph['id']}.jpg"
    flag = CACHE / "grabbed" / f"{ph['id']}.flag"
    if not flag.exists():
        api_get(ph["download"])
        flag.write_text("1")
        print(f"[download tracked] {ph['id']}")
    if not dest.exists():
        raw = ph["raw"]
        sep = "&" if "?" in raw else "?"
        url = f"{raw}{sep}w=1600&q=85&fm=jpg&fit=max"
        req = urllib.request.Request(url, headers={"User-Agent": "loam-ember-store/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
            f.write(r.read())
    meta = {
        "id": ph["id"],
        "photographer": ph["photographer"],
        "photographer_url": ph["photographer_url"],
        "photo_page": ph["photo_page"],
        "desc": ph["desc"],
        "query": data["query"],
        "source": "unsplash",
        "licence": "Unsplash License",
    }
    (CACHE / "grabbed" / f"{ph['id']}.json").write_text(json.dumps(meta))
    return dest, meta


def crop_4x5(im: Image.Image, zoom: float = 1.0) -> Image.Image:
    """Center crop to 4:5; zoom > 1 takes a tighter detail crop."""
    w, h = im.size
    target = 4 / 5
    if w / h > target:
        ch = h
        cw = int(h * target)
    else:
        cw = w
        ch = int(w / target)
    if zoom > 1.0:
        cw, ch = int(cw / zoom), int(ch / zoom)
    x = (w - cw) // 2
    y = (h - ch) // 2
    return im.crop((x, y, x + cw, y + ch))


def crop_wide(im: Image.Image, out_w: int, out_h: int) -> Image.Image:
    """Center crop to the widest frame of the given aspect the photo allows."""
    w, h = im.size
    target = out_w / out_h
    if w / h > target:
        ch = h
        cw = int(h * target)
    else:
        cw = w
        ch = int(w / target)
    x = (w - cw) // 2
    y = (h - ch) // 2
    return im.crop((x, y, x + cw, y + ch))


def encode(im: Image.Image, dest: Path, ceiling: int) -> None:
    q = 80
    while q >= 60:
        im.save(dest, "WEBP", quality=q, method=6)
        if dest.stat().st_size <= ceiling:
            return
        q -= 5
    raise SystemExit(f"cannot fit {dest.name} under {ceiling}B even at q60; pick a quieter photo")


def entry_for(sku: str, file: str, meta: dict, verdict: str, name: str = "") -> dict:
    return {
        "sku": sku,
        "file": file,
        "source": "unsplash",
        "photo_id": meta["id"],
        "photographer": meta["photographer"],
        "photographer_url": meta["photographer_url"],
        "photo_url": meta["photo_page"],
        "licence": "Unsplash License",
        "verdict": verdict,
        "name": name,
    }


def build_product(p: dict) -> list[dict]:
    """One product: main photo + optional gallery image."""
    src, meta = grab_full(p["search"], p["index"])
    im = Image.open(src).convert("RGB")
    main = crop_4x5(im).resize((LONG_W, LONG_H), Image.LANCZOS)
    main_dest = IMAGES / f"{p['sku']}.webp"
    encode(main, main_dest, MAX_BYTES)
    print(f"[ok] {main_dest.name} {main_dest.stat().st_size // 1024}KB ({meta['id']})")
    out = [entry_for(p["sku"], f"{p['sku']}.webp", meta,
                     p.get("verdict", ""), p.get("name", p["sku"]))]
    g = p.get("gallery", "crop")
    if g == "crop":
        detail = crop_4x5(im, zoom=1.6).resize((LONG_W, LONG_H), Image.LANCZOS)
        ddest = IMAGES / f"{p['sku']}-2.webp"
        encode(detail, ddest, MAX_BYTES)
        print(f"[ok] {ddest.name} {ddest.stat().st_size // 1024}KB (detail crop of {meta['id']})")
        out.append(entry_for(p["sku"], f"{p['sku']}-2.webp", meta,
                             f"detail crop of {meta['id']}", p.get("name", p["sku"])))
    elif g.startswith("photo:"):
        _, sname, sidx = g.split(":")
        gsrc, gmeta = grab_full(sname, int(sidx))
        gentry = second_photo(gsrc, p["sku"], gmeta, p.get("gverdict", ""), p.get("name", p["sku"]))
        out.append(gentry)
    return out


def second_photo(src: Path, sku: str, meta: dict, name: str, verdict: str = "") -> dict:
    im = Image.open(src).convert("RGB")
    main = crop_4x5(im).resize((LONG_W, LONG_H), Image.LANCZOS)
    ddest = IMAGES / f"{sku}-2.webp"
    encode(main, ddest, MAX_BYTES)
    print(f"[ok] {ddest.name} {ddest.stat().st_size // 1024}KB ({meta['id']})")
    return entry_for(sku, f"{sku}-2.webp", meta, verdict or "second photo", name)


def write_credits(entries: list[dict]) -> None:
    lines = [
        "# Image credits - Loam & Ember store",
        "",
        "Every product photograph is a real photograph sourced from Unsplash",
        "under the Unsplash License (free to use). Photographers are credited",
        "per file below and in the machine-readable manifest",
        "(artifacts/store-photos/manifest.json, gitignored; a committed copy",
        "ships at docs/IMAGE_CREDITS.md - this file).",
        "",
        "No identifiable faces, no visible text or logos, no brand names in any",
        "shipped photo (curation rule, STORE_DESIGN.md section 6).",
        "",
        "| File | SKU | Photographer | Photo | Licence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in entries:
        label = e["sku"]
        lines.append(
            f"| `{e['file']}` | {label} "
            f"| [{e['photographer']}]({e['photographer_url']}) "
            f"| [{e['photo_url']}]({e['photo_page']}) | Unsplash License |")
    CREDITS.write_text("\n".join(lines) + "\n")
    print(f"[ok] {CREDITS}")


def contact_sheet(entries: list[dict]) -> None:
    """All chosen photos beside their product names and SKUs, for review."""
    cell_w, cell_h, label_h, pad = 300, 375, 56, 10
    per = 6
    rows = (len(entries) + per - 1) // per
    W = per * (cell_w + pad) + pad
    H = rows * (cell_h + label_h + pad) + pad
    canvas = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(canvas)
    for k, e in enumerate(entries):
        f = IMAGES / e["file"]
        if not f.exists():
            continue
        col, row = k % per, k // per
        x = pad + col * (cell_w + pad)
        y = pad + row * (cell_h + label_h + pad)
        im = Image.open(f).convert("RGB")
        im.thumbnail((cell_w, cell_h))
        canvas.paste(im, (x, y))
        d.text((x, y + cell_h + 4), f"{e.get('name', e['sku'])}", fill="#000000")
        d.text((x, y + cell_h + 22), f"{e['sku']} - {e['photo_id']}", fill="#555555")
    CONTACT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(CONTACT)
    print(f"[ok] {CONTACT}")


def main() -> None:
    if not CHOICES.exists():
        sys.exit(f"no {CHOICES}; photo curation has not happened yet. "
                 "See docs/REVIEW_NEEDED_STORE.md.")
    choices = json.loads(CHOICES.read_text())
    IMAGES.mkdir(exist_ok=True)
    entries: list[dict] = []

    hero = choices.get("hero")
    if hero and hero.get("search"):
        src, meta = grab_full(hero["search"], hero["index"])
        him = crop_wide(Image.open(src).convert("RGB"), HERO_W, HERO_H)
        hdest = IMAGES / "hero.webp"
        encode(him, hdest, HERO_MAX)
        print(f"[ok] hero.webp {hdest.stat().st_size // 1024}KB ({meta['id']})")
        entries.append(entry_for("hero", "hero.webp", meta,
                                 hero.get("verdict", "hero lifestyle photo"), "hero"))

    for p in choices.get("products", []):
        entries.extend(build_product(p))

    MANIFEST_OUT.write_text(json.dumps({
        "note": "Machine-readable image manifest: one row per shipped file. "
                "The 600px variant is derived by WordPress from the 1200px "
                "master (image size urumi-600) and served via srcset.",
        "licence": "Unsplash License",
        "images": entries,
    }, indent=2))
    write_credits(entries)
    contact_sheet(entries)
    total = sum((IMAGES / e["file"]).stat().st_size for e in entries
                if (IMAGES / e["file"]).exists())
    print(f"[ok] {len(entries)} images, {total // 1024}KB total")


if __name__ == "__main__":
    main()
