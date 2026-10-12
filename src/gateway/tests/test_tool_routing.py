"""Tool namespacing + routing contract (docs/02 §3.2, docs/04 §6.2).

A client sees exactly one namespace: exposed tools are `slug__tool`; routing must split
on the FIRST `__`, reject unprefixed names, unknown slugs and disabled servers with a
concrete error (never a silent success).
"""

from __future__ import annotations

import uuid

import pytest

from gw_mcp.aggregator import exposed_name, split_exposed
from gw_mcp.breaker import CircuitBreaker

import gw_mcp.router as router
from tests.conftest import FakeDB, make_server


# ---- exposed name <-> slug split ----

def test_exposed_name_and_split_roundtrip():
    assert exposed_name("woo", "get_order") == "woo__get_order"
    assert split_exposed("woo__get_order") == ("woo", "get_order")


def test_split_takes_only_the_first_separator():
    # an upstream tool with __ inside its own name survives routing: the slug is
    # everything before the FIRST __
    assert split_exposed("woo__wc__get__order") == ("woo", "wc__get__order")


def test_split_rejects_unprefixed_or_empty_names():
    for bad in ["get_order", "__tool", "woo__", "", "__"]:
        with pytest.raises(ValueError):
            split_exposed(bad)


@pytest.mark.asyncio
async def test_routing_unknown_slug_raises(monkeypatch):
    db = FakeDB(servers=[])
    with pytest.raises(ValueError, match="Unknown server slug"):
        await router.call_tool_routed(db, "nosuch__tool", {})


@pytest.mark.asyncio
async def test_routing_disabled_server_raises(monkeypatch):
    srv = make_server(slug="woo", enabled=False)
    with pytest.raises(ValueError, match="disabled"):
        await router.call_tool_routed(FakeDB([srv]), "woo__list_products", {})


@pytest.mark.asyncio
async def test_routing_success_sets_connected_and_resets_breaker(monkeypatch):
    srv = make_server(slug="woo")
    breaker = CircuitBreaker()
    monkeypatch.setattr(router, "breaker", breaker)

    async def fake_proxy(server, tool, arguments, timeout_seconds=None):
        assert server.slug == "woo"
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    monkeypatch.setattr(router, "proxy_call", fake_proxy)
    result = await router.call_tool_routed(FakeDB([srv]), "woo__get_order", {"id": 1})
    assert result["isError"] is False and result["content"][0]["text"] == "ok"
    assert srv.status == "Connected" and srv.last_error is None
    assert breaker.state_for(srv.id) == "closed"
