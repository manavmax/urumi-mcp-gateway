"""LLM tool-schema sanitizer (docs/09).

The 11 cached tool schemas must be accepted by the function-calling dialect of the
configured LLM endpoint (Gemini's OpenAI-compatible endpoint). Gemini's schema parser
rejects a literal {"type": "null"} branch and the `const` keyword, both of which the
MCP/pydantic-produced schemas emit. The sanitizer must strip exactly those and leave
the meaning of every tool unchanged: same required fields, same enums, same bounds.

These are the REAL schemas as cached in the `tools` table, so a future schema change
that reintroduces an incompatible construct fails here.
"""

from __future__ import annotations

import json

from chat.agent import _sanitize_llm_schema, _to_openai_tools

# Mirrors of the 11 tools cached by the gateway (names + inputSchema only). Kept here
# so the test is hermetic (no DB, no network) yet tracks the live tool set.
TOOLS = [
    {
        "name": "notes__create_note",
        "inputSchema": {
            "type": "object", "title": "create_noteArguments",
            "required": ["title", "body"],
            "properties": {
                "body": {"type": "string", "title": "Body", "maxLength": 20000, "minLength": 1},
                "title": {"type": "string", "title": "Title", "maxLength": 200, "minLength": 1},
            },
        },
    },
    {
        "name": "notes__list_notes",
        "inputSchema": {"type": "object", "title": "list_notesArguments", "properties": {}},
    },
    {
        "name": "notes__search_notes",
        "inputSchema": {
            "type": "object", "title": "search_notesArguments",
            "required": ["query"],
            "properties": {"query": {"type": "string", "title": "Query", "maxLength": 200, "minLength": 1}},
        },
    },
    {
        "name": "time__convert_time",
        "inputSchema": {
            "type": "object", "title": "convert_timeArguments",
            "required": ["time", "from_tz", "to_tz"],
            "properties": {
                "time": {"type": "string", "title": "Time", "description": "ISO-8601 datetime, e.g. 2026-10-10T14:30:00"},
                "to_tz": {"type": "string", "title": "To Tz", "maxLength": 64, "minLength": 1, "description": "IANA timezone name, e.g. Europe/Berlin"},
                "from_tz": {"type": "string", "title": "From Tz", "maxLength": 64, "minLength": 1, "description": "IANA timezone name, e.g. Europe/Berlin"},
            },
        },
    },
    {
        "name": "time__get_current_time",
        "inputSchema": {
            "type": "object", "title": "get_current_timeArguments",
            "properties": {
                "timezone_name": {
                    "anyOf": [
                        {"type": "string", "maxLength": 64, "minLength": 1, "description": "IANA timezone name, e.g. Europe/Berlin"},
                        {"type": "null"},
                    ],
                    "title": "Timezone Name", "default": None,
                }
            },
        },
    },
    {
        "name": "woo__create_product",
        "inputSchema": {
            "type": "object", "title": "create_productArguments",
            "required": ["name", "regular_price"],
            "properties": {
                "sku": {"anyOf": [{"type": "string", "maxLength": 100}, {"type": "null"}], "title": "Sku", "default": None},
                "name": {"type": "string", "title": "Name", "maxLength": 200, "minLength": 1},
                "type": {"enum": ["simple", "variable", "grouped", "external"], "type": "string", "title": "Type", "default": "simple"},
                "description": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Description", "default": None, "description": "Long description"},
                "regular_price": {"type": "string", "title": "Regular Price", "pattern": "^\\d+(\\.\\d{1,2})?$"},
            },
        },
    },
    {
        "name": "woo__get_order",
        "inputSchema": {
            "type": "object", "title": "get_orderArguments",
            "required": ["id"],
            "properties": {"id": {"type": "integer", "title": "Id", "minimum": 1, "description": "WooCommerce order id"}},
        },
    },
    {
        "name": "woo__get_product",
        "inputSchema": {
            "type": "object", "title": "get_productArguments",
            "required": ["id"],
            "properties": {"id": {"type": "integer", "title": "Id", "minimum": 1, "description": "WooCommerce product id"}},
        },
    },
    {
        "name": "woo__list_orders",
        "inputSchema": {
            "type": "object", "title": "list_ordersArguments",
            "properties": {
                "page": {"type": "integer", "title": "Page", "default": 1, "minimum": 1, "description": "1-based page number"},
                "after": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "After", "default": None, "description": "ISO-8601 lower bound"},
                "before": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Before", "default": None, "description": "ISO-8601 upper bound"},
                "status": {
                    "anyOf": [
                        {"enum": ["pending", "processing", "on-hold", "completed", "cancelled", "refunded", "failed"], "type": "string"},
                        {"type": "string", "const": "any"},
                        {"type": "null"},
                    ],
                    "title": "Status", "default": None,
                },
                "per_page": {"type": "integer", "title": "Per Page", "default": 10, "maximum": 100, "minimum": 1, "description": "Page size (1-100)"},
            },
        },
    },
    {
        "name": "woo__list_products",
        "inputSchema": {
            "type": "object", "title": "list_productsArguments",
            "properties": {
                "sku": {"anyOf": [{"type": "string", "maxLength": 100}, {"type": "null"}], "title": "Sku", "default": None},
                "page": {"type": "integer", "title": "Page", "default": 1, "minimum": 1, "description": "1-based page number"},
                "search": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Search", "default": None, "description": "Free-text search"},
                "status": {"anyOf": [{"enum": ["publish", "draft", "pending", "private"], "type": "string"}, {"type": "null"}], "title": "Status", "default": None},
                "per_page": {"type": "integer", "title": "Per Page", "default": 10, "maximum": 100, "minimum": 1, "description": "Page size (1-100)"},
            },
        },
    },
    {
        "name": "woo__update_order_status",
        "inputSchema": {
            "type": "object", "title": "update_order_statusArguments",
            "required": ["id", "status"],
            "properties": {
                "id": {"type": "integer", "title": "Id", "minimum": 1, "description": "WooCommerce order id"},
                "status": {"enum": ["pending", "processing", "on-hold", "completed", "cancelled", "refunded", "failed"], "type": "string", "title": "Status"},
            },
        },
    },
]


def _walk(schema):
    """Yield every (key, value) pair, recursing through dicts and lists."""
    if isinstance(schema, dict):
        for k, v in schema.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(schema, list):
        for item in schema:
            yield from _walk(item)


def _all_required(schema):
    return set(schema.get("required", []))


def _has_null_branch(schema):
    for k, v in _walk(schema):
        if k == "type" and v == "null":
            return True
    return False


def test_no_const_keyword_in_any_sanitized_schema():
    for t in TOOLS:
        out = _sanitize_llm_schema(t["inputSchema"])
        assert not any(k == "const" for k, _ in _walk(out)), f"{t['name']} kept const"


def test_no_literal_null_type_branch_in_any_sanitized_schema():
    for t in TOOLS:
        out = _sanitize_llm_schema(t["inputSchema"])
        assert not _has_null_branch(out), f"{t['name']} kept a {{type:null}} branch"


def test_required_fields_preserved():
    for t in TOOLS:
        raw = t["inputSchema"]
        out = _sanitize_llm_schema(raw)
        assert _all_required(out) == _all_required(raw), f"{t['name']} required changed"


def test_optional_nullable_fields_stay_present_and_optional():
    # The null branch is dropped but the property itself must remain (just without the
    # null branch), and it must not have been added to required.
    for t in TOOLS:
        raw = t["inputSchema"]
        out = _sanitize_llm_schema(raw)
        for prop, spec in raw.get("properties", {}).items():
            if isinstance(spec, dict) and "anyOf" in spec and any(
                b.get("type") == "null" for b in spec["anyOf"]
            ):
                assert prop in out.get("properties", {}), f"{t['name']} lost property {prop}"
                assert prop not in _all_required(out), f"{t['name']} made optional {prop} required"


def test_enums_preserved():
    for t in TOOLS:
        out = _sanitize_llm_schema(t["inputSchema"])
        for k, v in _walk(out):
            if k == "enum":
                # enum sets must survive unchanged (they define the accepted values)
                assert isinstance(v, list) and len(v) >= 1


def test_list_orders_status_keeps_enum_and_free_string_branches():
    # woo__list_orders.status is the trickiest: enum + const "any" + null. After
    # sanitizing, the null branch is gone and the const is dropped, but the enum branch
    # AND the free-string ("any") branch must both remain, so "any" is still accepted.
    raw = next(t["inputSchema"] for t in TOOLS if t["name"] == "woo__list_orders")
    out = _sanitize_llm_schema(raw)
    status = out["properties"]["status"]
    branches = status.get("anyOf")
    assert branches is not None, "status should keep multiple branches"
    kinds = sorted(b.get("type") for b in branches)
    assert "null" not in kinds, "null branch must be dropped"
    assert "string" in kinds
    enums = [b.get("enum") for b in branches if "enum" in b]
    assert enums, "enum branch must be preserved"
    assert "pending" in enums[0] and "failed" in enums[0]


def test_single_null_branch_inlines_to_plain_type():
    # time__get_current_time.timezone_name has anyOf [ {type:string}, {type:null} ].
    # After sanitizing it should collapse to a plain string (still optional).
    raw = next(t["inputSchema"] for t in TOOLS if t["name"] == "time__get_current_time")
    out = _sanitize_llm_schema(raw)
    prop = out["properties"]["timezone_name"]
    assert "anyOf" not in prop, "single surviving branch should be inlined"
    assert prop.get("type") == "string"
    assert "timezone_name" not in _all_required(out)


def test_empty_properties_schema_untouched():
    raw = {"type": "object", "title": "list_notesArguments", "properties": {}}
    out = _sanitize_llm_schema(raw)
    assert out == raw


def test_to_openai_tools_applies_sanitizer_and_keeps_shape():
    tools = _to_openai_tools(TOOLS)
    assert len(tools) == 11
    for fn in tools:
        assert fn["type"] == "function"
        assert "name" in fn["function"]
        params = fn["function"]["parameters"]
        assert isinstance(params, dict)
        assert not _has_null_branch(params), f"{fn['function']['name']} unsanitized"


def test_sanitized_schemas_are_valid_json():
    for t in TOOLS:
        out = _sanitize_llm_schema(t["inputSchema"])
        json.dumps(out)  # must serialize without error
