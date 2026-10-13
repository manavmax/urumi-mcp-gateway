"""Blank optional arguments must behave like omitted ones (Test 2 regression).

The MCP Inspector renders a text input for every string parameter and submits
`""` for the fields the user leaves empty. Before the fix, `status=""` failed
FastMCP's schema validation (Literal) and `timezone_name=""` failed `min_length`,
so an otherwise-empty `list_orders` / `list_products` / `get_current_time` call
came back `isError: true` instead of a result.

These tests drive the real FastMCP servers over the in-memory MCP transport with a
fake Woo client, so the assertions cover actual tool-call argument handling.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from tools import register_tools


class FakeWooClient:
    """Records calls and returns empty pages — enough to prove argument handling."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def get(self, path, params=None, resource=None):
        self.calls.append((path, dict(params or {})))
        return []

    async def post(self, path, json_body=None, resource=None):
        self.calls.append((path, dict(json_body or {})))
        return {"id": 1, "name": json_body.get("name"), "price": "1.00", "sku": json_body.get("sku"), "permalink": ""}


@asynccontextmanager
async def woo_session():
    client = FakeWooClient()
    mcp = FastMCP("woo-test")
    register_tools(mcp, client)
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        yield session, client


def _text(result) -> str:
    return result.content[0].text if result.content else ""


def _payload(result) -> dict:
    return json.loads(_text(result))


@pytest.mark.asyncio
async def test_list_orders_blank_optional_strings_are_not_provided():
    async with woo_session() as (session, client):
        result = await session.call_tool("list_orders", {"after": "", "before": "", "status": ""})
        assert result.isError is False, _text(result)
        assert _payload(result) == {"orders": [], "count": 0}
        # the upstream request must carry only pagination — no empty filters
        path, params = client.calls[-1]
        assert path == "wp-json/wc/v3/orders"
        assert params == {"per_page": 10, "page": 1}


@pytest.mark.asyncio
async def test_list_products_blank_optional_strings_are_not_provided():
    async with woo_session() as (session, client):
        result = await session.call_tool("list_products", {"search": "", "status": "", "sku": ""})
        assert result.isError is False, _text(result)
        path, params = client.calls[-1]
        assert path == "wp-json/wc/v3/products"
        assert params == {"per_page": 10, "page": 1}


@pytest.mark.asyncio
async def test_list_orders_real_values_still_pass_through():
    async with woo_session() as (session, client):
        result = await session.call_tool(
            "list_orders",
            {"after": "2026-01-01T00:00:00", "before": "", "status": "any", "per_page": 5},
        )
        assert result.isError is False, _text(result)
        _path, params = client.calls[-1]
        assert params == {"per_page": 5, "page": 1, "after": "2026-01-01T00:00:00", "status": "any"}


@pytest.mark.asyncio
async def test_list_orders_invalid_status_still_rejected():
    """A non-empty but invalid status is a real client error, not a blank slip."""
    async with woo_session() as (session, _client):
        result = await session.call_tool("list_orders", {"status": "definitely-not-a-status"})
        assert result.isError is True


@pytest.mark.asyncio
async def test_create_product_blank_optional_fields_are_not_provided():
    async with woo_session() as (session, client):
        result = await session.call_tool(
            "create_product",
            {"name": "Blank Opt", "regular_price": "9.99", "description": "", "sku": ""},
        )
        assert result.isError is False, _text(result)
        _path, body = client.calls[-1]
        assert "sku" not in body and body["description"] == ""
