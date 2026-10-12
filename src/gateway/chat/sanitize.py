"""Sanitize tool output before feeding back to LLM / browser."""

import re

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous\s+instructions", re.I),
    re.compile(r"system\s*:", re.I),
    re.compile(r"^#{2,}\s*system", re.I | re.M),
]

MAX_TOOL_OUTPUT = 20_000


def sanitize(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    if not text:
        return ""
    # strip obvious prompt-injection markers
    for pat in _INJECTION_PATTERNS:
        text = pat.sub("[filtered]", text)
    if len(text) > limit:
        text = text[:limit] + f"\n...[truncated {len(text) - limit} chars; use pagination]"
    return text
