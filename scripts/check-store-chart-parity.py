#!/usr/bin/env python3
"""Drift guard: the store chart's seeding must match the main chart's.

The main chart (helm/templates/jobs/wp-setup.yaml) and the per-store chart
(helm/store/templates/jobs/wp-setup.yaml) each carry a COPY of the WordPress
seed + storefront configuration. The duplication is deliberate for now (the
provisioner image bakes helm/store; the shared-script refactor is the later
option, docs/DECISIONS.md ADR-083) - which means the two copies can drift
silently. They did once: the store chart froze at the pre-store-v2 seed while
the catalog moved to slug-referenced categories, so provisioned stores got 29
products stuck in "Uncategorized" and empty collection pages.

This check extracts the visitor-visible seeding blocks from both charts and
fails when they differ:

  1. wp-setup seed block:   "# --- Seed products BY SKU" .. before
                            'echo "Final product list:"'  (the category terms,
                            product data model, images, theme activation,
                            brand, pages, primary menu, Woo options)
  2. store-assets block:    'echo "Copying store assets' .. 'store assets copied.'
                            in deployment-wordpress.yaml (catalog, photos
                            manifest and images copied onto wp-content)

Whitespace is normalized (indentation + trailing spaces + blank lines), so
only real content differences fail.

HOW TO UPDATE
------------
- If you change the seed logic, change BOTH charts identically (edit one,
  copy the block to the other) and re-run this script.
- If a line genuinely must differ per chart (a store-specific value), add a
  regex to ALLOWLIST below matching that normalized line; the line is then
  dropped from both sides before comparison. Keep the list short and comment
  each entry with WHY it is store-specific. Do not use it to silence a
  forgotten copy - a rule that is not obviously store-specific will be
  rejected in review.
- Run: python3 scripts/check-store-chart-parity.py  (also wired into
  `make lint` and `make chart-parity`).
"""

import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Compared file pairs: (main-chart path, store-chart path)
PAIRS = [
    ("helm/templates/jobs/wp-setup.yaml", "helm/store/templates/jobs/wp-setup.yaml"),
    ("helm/templates/deployment-wordpress.yaml", "helm/store/templates/deployment-wordpress.yaml"),
]

# Blocks inside the compared files: (start marker, end marker, end_inclusive).
# The seed block covers everything a store visitor sees that the job seeds.
BLOCKS = {
    "helm/templates/jobs/wp-setup.yaml": [
        ("# --- Seed products BY SKU", 'echo "Final product list:"', False),
    ],
    "helm/templates/deployment-wordpress.yaml": [
        ('echo "Copying store assets', "store assets copied.", True),
    ],
}

# Explicit allow-list of known store-specific lines (normalized form).
# A line matching any regex is dropped from BOTH charts before comparison.
# TODAY THIS IS EMPTY: the seeding blocks are byte-identical.
ALLOWLIST = [
    # Example (store-specific admin default, hypothetical):
    # re.compile(r"^ADMIN_USER= .*$"),
]


def normalize(lines):
    """Collapse whitespace so only content differences remain."""
    out = []
    for line in lines:
        text = re.sub(r"\s+", " ", line).strip()
        if not text:
            continue
        if any(rx.search(text) for rx in ALLOWLIST):
            continue
        out.append(text)
    return out


def extract(path, blocks):
    lines = Path(path).read_text().splitlines()
    extracted = []
    for start_marker, end_marker, end_inclusive in blocks:
        try:
            start = next(i for i, line in enumerate(lines) if start_marker in line)
        except StopIteration:
            sys.exit(f"FAIL {path}: start marker not found: {start_marker!r}")
        try:
            end = next(i for i, line in enumerate(lines[start + 1:], start + 1) if end_marker in line)
        except StopIteration:
            sys.exit(f"FAIL {path}: end marker not found: {end_marker!r}")
        block = lines[start : end + 1] if end_inclusive else lines[start:end]
        extracted.extend(block)
    return extracted


def main():
    failed = False
    for main_path, store_path in PAIRS:
        blocks = BLOCKS[main_path]
        main_block = normalize(extract(ROOT / main_path, blocks))
        store_block = normalize(extract(ROOT / store_path, blocks))
        if main_block == store_block:
            print(f"OK   {store_path}: seeding blocks match {main_path}")
            continue
        failed = True
        print(f"DRIFT {store_path} vs {main_path}:")
        for line in difflib.unified_diff(
            main_block, store_block, fromfile=f"main/{main_path}", tofile=f"store/{store_path}", lineterm=""
        ):
            print(f"  {line}")
        print(
            "  -> fix: copy the seeding block from the main chart into the store chart\n"
            "     (they must seed identical visitor-visible content), or add a\n"
            "     store-specific line to ALLOWLIST in scripts/check-store-chart-parity.py\n"
            "     if (and only if) the line is genuinely store-specific. See the script\n"
            "     docstring for how to update it."
        )
    if failed:
        sys.exit(1)
    print("store chart parity: OK")


if __name__ == "__main__":
    main()
