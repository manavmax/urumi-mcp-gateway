#!/usr/bin/env python3
"""Unsplash sourcing for the Loam & Ember store (throwaway tool, NOT committed logic
that ever runs in an image; lives under scripts/ but reads only .unsplash_key).

Reads the Access Key from .unsplash_key in the worktree root. The key is NEVER
printed, echoed, logged or written anywhere. Search responses are cached in
artifacts/store-photos/cache/ (gitignored) so re-runs do not burn the 50 req/h
demo budget. Candidate previews are downloaded at small size (CDN, uncounted);
only CHOSEN photos trigger links.download_location (counts against the quota).

Usage:
  fetch.py search <name> <query> [per_page]   # one search, cached
  fetch.py previews <name> [n]                 # download small previews of top n results
  fetch.py grab <name> <index> <out.jpg>       # download_location + raw w=1600 for one chosen photo
"""
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "artifacts" / "store-photos" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)


def key() -> str:
    k = (ROOT / ".unsplash_key").read_text(encoding="utf-8").strip()
    if not k:
        sys.exit("empty key file")
    return k


def api(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Client-ID {key()}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def search(name: str, query: str, per_page: int = 30) -> None:
    cache_file = CACHE / f"search-{name}.json"
    if cache_file.exists():
        print(f"[cache] search-{name}.json already cached; not spending an API call")
        return
    q = urllib.parse.quote(query)
    data = api(f"https://api.unsplash.com/search/photos?query={q}&orientation=portrait&content_filter=high&per_page={per_page}")
    slim = []
    for i, ph in enumerate(data.get("results", [])):
        slim.append({
            "i": i,
            "id": ph["id"],
            "w": ph["width"], "h": ph["height"],
            "desc": (ph.get("description") or ph.get("alt_description") or "")[:110],
            "color": ph.get("color"),
            "small": ph["urls"]["small"],
            "raw": ph["urls"]["raw"],
            "download": ph["links"]["download_location"],
            "photographer": ph["user"]["name"],
            "photographer_url": ph["user"]["links"]["html"],
            "photo_page": ph["links"]["html"],
        })
    cache_file.write_text(json.dumps({"query": query, "total": data.get("total"), "results": slim}, indent=1))
    print(f"[ok] {name}: cached {len(slim)} results for query {query!r} (total on Unsplash: {data.get('total')})")


def previews(name: str, n: int = 20) -> None:
    cache_file = CACHE / f"search-{name}.json"
    if not cache_file.exists():
        sys.exit(f"no cached search {name}; run search first")
    data = json.loads(cache_file.read_text())
    out = CACHE / "previews" / name
    out.mkdir(parents=True, exist_ok=True)
    for ph in data["results"][:n]:
        dest = out / f"{ph['i']:02d}.jpg"
        if dest.exists():
            continue
        try:
            urllib.request.urlretrieve(ph["small"], dest)
        except Exception as e:  # noqa: BLE001
            print(f"  preview fail {name}/{ph['i']}: {e}")
        time.sleep(0.15)
    print(f"[ok] previews for {name}: {n} files in {out}")


def grab_cmd(name: str, i: int, out_file: str) -> None:
    cache_file = CACHE / f"search-{name}.json"
    data = json.loads(cache_file.read_text())
    ph = next(p for p in data["results"] if p["i"] == i)
    marker = CACHE / "grabbed" / f"{ph['id']}.flag"
    if not marker.exists():
        # Unsplash requires triggering the download endpoint to count a download.
        api(ph["download"])
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1")
        print(f"[download tracked] {ph['id']}")
    raw = ph["raw"]
    sep = "&" if "?" in raw else "?"
    url = f"{raw}{sep}w=1600&q=80&fm=jpg&fit=max"
    req = urllib.request.Request(url, headers={"User-Agent": "loam-ember-store/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(out_file, "wb") as f:
        f.write(r.read())
    meta = {"id": ph["id"], "photographer": ph["photographer"], "photographer_url": ph["photographer_url"],
            "photo_page": ph["photo_page"], "desc": ph["desc"], "query": data["query"]}
    (CACHE / "grabbed" / f"{ph['id']}.json").write_text(json.dumps(meta))
    print(f"[ok] saved {out_file} ({ph['id']})")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "search":
        search(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 30)
    elif cmd == "previews":
        previews(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 20)
    elif cmd == "grab":
        grab_cmd(sys.argv[2], int(sys.argv[3]), sys.argv[4])
    else:
        sys.exit(__doc__)
