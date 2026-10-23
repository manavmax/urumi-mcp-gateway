#!/usr/bin/env python3
"""Regenerate scripts/demo-seeds.json from store/products.json.

The demo-reset keep-manifest (ADR-032/073) must list every parent SKU of the
live catalog with name, price and type, so `make demo-reset` keeps exactly the
catalog and deletes everything else. Run this after any products.json rebuild
(so after photo curation rebuilds the catalogue):

    python3 scripts/regen-demo-seeds.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = ROOT / "store" / "products.json"
SEEDS = ROOT / "scripts" / "demo-seeds.json"


def main() -> None:
    data = json.loads(PRODUCTS.read_text())
    out = []
    for p in data["products"]:
        out.append({
            "sku": p["sku"],
            "name": p["name"],
            "price": p["price"],
            "type": "variable" if p.get("variations") else "simple",
        })
    doc = {
        "note": "Keep-manifest for make demo-reset (ADR-032/073). Regenerate with "
                "scripts/regen-demo-seeds.py after rebuilding products.json. Any "
                "product NOT listed here is deleted by the demo reset; the media "
                "rule keeps thumbnails and gallery images of kept products.",
        "brand": data.get("brand", "Loam & Ember"),
        "products": out,
    }
    SEEDS.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"[ok] {SEEDS}: {len(out)} parent SKUs")


if __name__ == "__main__":
    main()
