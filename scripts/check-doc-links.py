#!/usr/bin/env python3
"""Doc link checker (stdlib only).

Fails when a link in user-facing docs points at a repo file that does not
exist. Checks:
  1. relative markdown links and images in README.md and docs/*.md
     (skips URLs, anchors, mailto; resolves ../ against the file's dir)
  2. data-repo-path attributes in src/landing/index.html (the landing builds
     github blob/main/<path> links at runtime from this single attribute)
  3. inline github.com blob/main/<path> links anywhere in README, docs and
     the landing HTML

Exit 0 with a count summary, or exit 1 listing every broken path.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
BLOB_MAIN = re.compile(r"""github\.com/[^/\s"']+/[^/\s"']+/blob/main/([^\s)#?'"]+)""")
REPO_PATH = re.compile(r'data-repo-path="([^"]+)"')
BAD_SCHEME = ("http://", "https://", "mailto:", "#")


def markdown_targets(text: str) -> list[str]:
    return [m.group(1) for m in MD_LINK.finditer(text) if not m.group(1).startswith(BAD_SCHEME)]


def check() -> list[str]:
    problems: list[str] = []

    def repo_ok(path: str) -> bool:
        return (ROOT / path).exists()

    def relative_ok(source: Path, target: str) -> bool:
        clean = target.split("#", 1)[0]
        if not clean or clean.startswith(BAD_SCHEME):
            return True
        return (source.parent / clean).resolve().is_file()

    # 1 + 2: markdown links in root README and docs/, plus data-repo-path in the landing page
    md_files = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    for md in md_files:
        text = md.read_text(encoding="utf-8", errors="replace")
        for target in markdown_targets(text):
            if not relative_ok(md, target):
                problems.append(f"{md.relative_to(ROOT)}: broken markdown link -> {target}")
    landing = ROOT / "src/landing/index.html"
    if landing.exists():
        html = landing.read_text(encoding="utf-8", errors="replace")
        for path in REPO_PATH.findall(html):
            if not repo_ok(path):
                problems.append(f"src/landing/index.html: data-repo-path missing in repo -> {path}")
        # 3: any hardcoded blob/main link in the html (there should be none; built at runtime)
        for path in BLOB_MAIN.findall(html):
            if not repo_ok(path):
                problems.append(f"src/landing/index.html: blob/main path missing in repo -> {path}")

    # 3: hardcoded blob/main links anywhere in the checked docs
    for md in md_files:
        text = md.read_text(encoding="utf-8", errors="replace")
        for path in BLOB_MAIN.findall(text):
            if not repo_ok(path):
                problems.append(f"{md.relative_to(ROOT)}: blob/main path missing in repo -> {path}")

    return problems


def main() -> int:
    problems = check()
    if problems:
        print("DOC LINK CHECK FAILED:")
        for p in problems:
            print(f"  {p}")
        return 1
    print("doc links: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
