#!/usr/bin/env python3
"""Prose style checker for user facing docs (stdlib only).

Enforces the repository prose rules on README.md, THREAT_MODEL.md,
SYSTEM_DESIGN_AND_TRADEOFFS.md and every docs/*.md file:

  1. no em dashes, en dashes or similar dash glyphs used as punctuation
  2. no " - " (spaced hyphen) used as punctuation in a prose line
  3. no hyphenated compound words in prose (write "read only", "built in",
     "per user"), matching letter(s) hyphen letter(s)
  4. no emojis anywhere in these files

Exemptions (never flagged): fenced code blocks; inline code spans including
ones that cross line breaks; markdown link/image targets; URLs; list markers;
table separator rows; HTML comments; reference link definitions.

Exit 0 when clean; exit 1 listing every violation with file, line and rule.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DASHES = "\u2012\u2013\u2014\u2015\u2212"

EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u2049\u203C\u2122\u2139]")

SPACED_HYPHEN = re.compile(r"(?<=\S)\s-\s(?=\S)")
HYPHENATED = re.compile(r"[A-Za-z][A-Za-z0-9]*-[A-Za-z][A-Za-z0-9-]*[A-Za-z0-9]|[A-Za-z][A-Za-z0-9]*-[A-Za-z]")

URL = re.compile(r"(?:https?://[^\s)\]>\"']+|<https?://[^>]+>|mailto:[^\s)\]>\"']+)")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
HTML_TAG = re.compile(r"<[^>]*>")
REF_DEF = re.compile(r"^\s*\[[^\]]+\]:\s+\S+")
LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def is_separator_row(raw: str) -> bool:
    s = raw.strip()
    return "|" in s and set(s) <= set("|-: \t") and "-" in s


def strip_exemptions(line: str) -> str:
    out = URL.sub(" ", line)
    out = LINK_TARGET.sub(" ", out)
    return out


def check_file(path: Path) -> list[str]:
    return check_text(path, path.read_text(encoding="utf-8", errors="replace"))


def check_text(path: Path, text: str) -> list[str]:
    problems: list[str] = []
    # 1. emoji rule applies to every line, code included
    for i, line in enumerate(text.split("\n"), 1):
        for ch in line:
            if EMOJI.match(ch):
                problems.append(f"{path.name}:{i}: emoji/symbol glyph U+{ord(ch):04X} ({unicodedata.name(ch, '?')})")
                break
    # 2/3. dash, spaced hyphen and hyphenated word rules on prose only
    in_fence = in_code = False
    for lineno, raw in enumerate(text.split("\n"), 1):
        s = raw.strip()
        if in_fence:
            if s.startswith("```") or s.startswith("~~~"):
                in_fence = False
            continue
        if s.startswith("```") or s.startswith("~~~"):
            in_fence = True
            continue
        parts = raw.split("`")
        if in_code:
            # starts inside a code span; prose resumes after the closing backtick
            if len(parts) % 2 == 0:  # odd number of backticks closes the span
                in_code = False
                segs = parts[1::2]
            else:
                segs = []
        else:
            if len(parts) % 2 == 0:  # odd backtick count: span continues next line
                in_code = True
            segs = parts[0::2]
        prose = " ".join(segs)
        stripped = raw.strip()
        if not stripped or stripped.startswith("<!--") or REF_DEF.match(stripped):
            continue
        if is_separator_row(raw):
            continue
        prose = URL.sub(" ", prose)
        prose = LINK_TARGET.sub(" ", prose)
        if stripped.startswith("<"):
            prose = HTML_TAG.sub(" ", prose)
        prose = LIST_MARKER.sub("", prose, count=1)
        for ch in prose:
            if ch in DASHES:
                problems.append(f"{path.name}:{lineno}: dash glyph {ch!r} ({unicodedata.name(ch)}) used as punctuation")
                break
        m = SPACED_HYPHEN.search(prose)
        if m:
            ctx = prose[max(0, m.start() - 25):m.end() + 25].strip()
            problems.append(f"{path.name}:{lineno}: spaced hyphen used as punctuation: ...{ctx}...")
        m = HYPHENATED.search(prose)
        if m:
            ctx = prose[max(0, m.start() - 25):m.end() + 25].strip()
            problems.append(f"{path.name}:{lineno}: hyphenated word {m.group(0)!r} in prose: ...{ctx}...")
    return problems


def main() -> int:
    files = [ROOT / "README.md", ROOT / "THREAT_MODEL.md", ROOT / "SYSTEM_DESIGN_AND_TRADEOFFS.md"]
    files += sorted((ROOT / "docs").glob("*.md"))
    problems: list[str] = []
    for f in files:
        if f.exists():
            problems.extend(check_file(f))
    if problems:
        print(f"PROSE STYLE CHECK FAILED ({len(problems)} finding(s)):")
        for p in problems[:200]:
            print(f"  {p}")
        if len(problems) > 200:
            print(f"  ... and {len(problems) - 200} more")
        return 1
    print(f"prose style: OK ({len(files)} files checked: no dashes, no hyphenated prose, no emojis)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
