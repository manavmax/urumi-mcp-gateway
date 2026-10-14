"""Sanitize tool output before feeding back to LLM / browser.

Security note: `_sanitize` is a WEAK blocklist — one layer only. It catches
obvious `ignore previous instructions` / `system:` markers but cannot stop a
determined injection hidden in tool output (e.g. in an order note or a note
body). The real boundary is the MESSAGE ROLE + the per-turn envelope: tool
output never becomes a `system`/`assistant` instruction message. It is placed
in a `role: tool` message, or — when the provider rejects the tool-call echo
(Gemini thought_signature 400) — re-presented as a `role: user` message that
carries the SAME wrapped envelope verbatim. In both roles it stays data. See
`chat/agent.py:wrap_tool_output` / `_build_recovery_message` and
docs/THREAT_MODEL.md.
"""

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
    # Weak blocklist — best-effort only. The role + delimiter/JSON envelope is
    # the real isolation; this just trims the obvious markers.
    for pat in _INJECTION_PATTERNS:
        text = pat.sub("[filtered]", text)
    if len(text) > limit:
        text = text[:limit] + f"\n...[truncated {len(text) - limit} chars; use pagination]"
    return text

