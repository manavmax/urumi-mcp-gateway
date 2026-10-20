"""ADR-054: get_current_time honours the configured default timezone.

When the caller omits timezone_name (or submits ""), the tool answers in the
zone from env DEFAULT_TIMEZONE (Helm demoTime.defaultTimezone) instead of a
hardcoded UTC.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import tools
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from tools import register_tools


@asynccontextmanager
async def time_session(monkeypatch=None, default_tz: str = "UTC"):
    mcp = FastMCP("demo-time-test")
    if monkeypatch is not None:
        monkeypatch.setattr(
            tools,
            "get_settings",
            lambda: SimpleNamespace(default_timezone=default_tz),
        )
    register_tools(mcp)
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        yield session


def _text(result) -> str:
    return result.content[0].text if result.content else ""


@pytest.mark.asyncio
async def test_omitted_timezone_uses_configured_default(monkeypatch):
    async with time_session(monkeypatch, default_tz="Asia/Kolkata") as session:
        result = await session.call_tool("get_current_time", {})
        assert result.isError is False, _text(result)
        payload = json.loads(_text(result))
        assert payload["timezone"] == "Asia/Kolkata"
        assert payload["utc_offset_minutes"] == 330  # +05:30


@pytest.mark.asyncio
async def test_blank_timezone_uses_configured_default(monkeypatch):
    """The Inspector's "" for an empty optional field behaves like an omitted one."""
    async with time_session(monkeypatch, default_tz="Asia/Kolkata") as session:
        result = await session.call_tool("get_current_time", {"timezone_name": ""})
        assert result.isError is False, _text(result)
        payload = json.loads(_text(result))
        assert payload["timezone"] == "Asia/Kolkata"


@pytest.mark.asyncio
async def test_explicit_timezone_still_wins(monkeypatch):
    async with time_session(monkeypatch, default_tz="Asia/Kolkata") as session:
        result = await session.call_tool("get_current_time", {"timezone_name": "Europe/Berlin"})
        assert result.isError is False, _text(result)
        assert json.loads(_text(result))["timezone"] == "Europe/Berlin"


@pytest.mark.asyncio
async def test_invalid_default_errors_clearly(monkeypatch):
    """A misconfigured DEFAULT_TIMEZONE surfaces as the tool's normal clear error
    (same shape as an unknown caller-supplied zone), never a crash."""
    async with time_session(monkeypatch, default_tz="Not/AZone") as session:
        result = await session.call_tool("get_current_time", {})
        assert result.isError is True
        assert "Unknown timezone" in _text(result)


@pytest.mark.asyncio
async def test_utc_default_preserved(monkeypatch):
    """With the historical default (UTC) the payload is unchanged."""
    async with time_session(monkeypatch, default_tz="UTC") as session:
        result = await session.call_tool("get_current_time", {})
        assert result.isError is False, _text(result)
        payload = json.loads(_text(result))
        assert payload["timezone"] == "UTC" and payload["utc_offset_minutes"] == 0
