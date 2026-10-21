"""Compact mode: two meta tools instead of hundreds (Phase 3, ADR-058).

When a client selects compact mode (X-Gateway-Mode: compact or ?mode=compact),
tools/list returns ONLY:

  gateway__search_tools(query, limit?)   keyword ranking over the RBAC-filtered
                                         tool list (name + description)
  gateway__call_tool(name, arguments)    invoke a real tool through the SAME
                                         routing / permission / timeout / audit
                                         code path - the audit row carries the
                                         REAL tool name

Default mode is untouched. The meta tools themselves are plain MCP tool
definitions, so any MCP client can use them without protocol changes.
"""

from __future__ import annotations

import json
import re

META_PREFIX = "gateway__"
SEARCH_TOOL_NAME = "gateway__search_tools"
CALL_TOOL_NAME = "gateway__call_tool"

DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50

COMPACT_SEARCH_TOOL = {
    "name": SEARCH_TOOL_NAME,
    "description": (
        "Search the gateway's tool catalogue by keywords over tool names and "
        "descriptions. Returns the best matches with their full names, "
        "descriptions and input schemas. Call gateway__call_tool with the "
        "returned name to invoke one. Only tools you are allowed to call are "
        "searchable."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords, space separated"},
            "limit": {
                "type": "integer",
                "description": f"Maximum matches (default {DEFAULT_SEARCH_LIMIT}, max {MAX_SEARCH_LIMIT})",
                "minimum": 1,
                "maximum": MAX_SEARCH_LIMIT,
            },
        },
        "required": ["query"],
    },
}

COMPACT_CALL_TOOL = {
    "name": CALL_TOOL_NAME,
    "description": (
        "Invoke a tool by its full gateway name (e.g. woo__list_orders). Use "
        "gateway__search_tools to find names and schemas. Arguments must match "
        "the tool's input schema."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Full tool name, e.g. woo__list_orders"},
            "arguments": {"type": "object", "description": "The tool's input arguments"},
        },
        "required": ["name"],
    },
}

COMPACT_TOOLS = [COMPACT_SEARCH_TOOL, COMPACT_CALL_TOOL]


def is_meta_tool(name: str) -> bool:
    return name in (SEARCH_TOOL_NAME, CALL_TOOL_NAME)


def compact_mode_selected(header_value: str | None, query_value: str | None) -> bool:
    """X-Gateway-Mode header or ?mode= query parameter, exact match."""
    return (header_value or "").strip().lower() == "compact" or (query_value or "").strip().lower() == "compact"


def _score(tool: dict, terms: list[str]) -> int:
    """Simple, explainable keyword ranking. Name hits dominate description hits.

    10 exact name match, 8 name starts-with, 5 whole word in name,
    3 whole word in description, 1 substring anywhere; sums across terms.
    """
    name = (tool.get("name") or "").lower()
    description = (tool.get("description") or "").lower()
    score = 0
    for term in terms:
        if name == term:
            score += 10
        elif name.startswith(term):
            score += 8
        elif re.search(rf"\b{re.escape(term)}\b", name):
            score += 5
        if re.search(rf"\b{re.escape(term)}\b", description):
            score += 3
        elif term in description:
            score += 1
    return score


def search_tools(tools: list[dict], query: str, limit: int | None = None) -> list[dict]:
    """Rank the (already RBAC-filtered) tool list against the query keywords.

    Returns the top `limit` tools (default 20, max 50) with score >= 1, each
    carrying name, description and inputSchema. A blank query returns the first
    `limit` tools (a plain catalogue listing).
    """
    limit = DEFAULT_SEARCH_LIMIT if not limit or limit < 1 else min(limit, MAX_SEARCH_LIMIT)
    terms = [t for t in (query or "").lower().split() if t]
    if not terms:
        return [
            {"name": t.get("name"), "description": t.get("description") or "", "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}}}
            for t in tools[:limit]
        ]
    scored = sorted(
        ((_score(t, terms), t) for t in tools),
        key=lambda pair: (-pair[0], pair[1].get("name") or ""),
    )
    return [
        {"name": t.get("name"), "description": t.get("description") or "", "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}}}
        for score, t in scored
        if score >= 1
    ][:limit]


def search_result_content(matches: list[dict], query: str) -> dict:
    """The MCP CallToolResult payload for gateway__search_tools."""
    payload = {
        "query": query,
        "matches": matches,
        "count": len(matches),
        "hint": "call gateway__call_tool with a returned name to invoke it",
    }
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}
