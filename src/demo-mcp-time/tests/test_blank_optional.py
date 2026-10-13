"""Blank optional arguments must behave like omitted ones (Test 2 regression).

The MCP Inspector submits `""` for every string parameter the user leaves empty, so
`timezone_name=""` used to fail the `min_length=1` schema check instead of falling
back to UTC. Required arguments (convert_time) must keep rejecting blanks.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from tools import register_tools


@asynccontextmanager
async def time_session():
    mcp = FastMCP("demo-time-test")
    register_tools(mcp)
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        yield session


def _text(result) -> str:
    return result.content[0].text if result.content else ""


@pytest.mark.asyncio
async def test_get_current_time_blank_timezone_defaults_to_utc():
    async with time_session() as session:
        result = await session.call_tool("get_current_time", {"timezone_name": ""})
        assert result.isError is False, _text(result)
        payload = json.loads(_text(result))
        assert payload["timezone"] == "UTC" and payload["utc_offset_minutes"] == 0


@pytest.mark.asyncio
async def test_get_current_time_real_timezone_still_works():
    async with time_session() as session:
        result = await session.call_tool("get_current_time", {"timezone_name": "Europe/Berlin"})
        assert result.isError is False, _text(result)
        assert json.loads(_text(result))["timezone"] == "Europe/Berlin"


@pytest.mark.asyncio
async def test_convert_time_required_blanks_still_rejected():
    """A blank REQUIRED argument is a client error — the blank-tolerance rule only
    applies to optional parameters."""
    async with time_session() as session:
        result = await session.call_tool(
            "convert_time", {"time": "", "from_tz": "UTC", "to_tz": "UTC"}
        )
        assert result.isError is True
