"""Timeout isolation + circuit breaker (docs/02 §3.3, docs/04 §6.2).

One slow or dead upstream must never block another: each tools/call runs under its own
`asyncio.wait_for` bounded by the server's timeout, and repeated failures open only that
server's circuit. proxy_call is monkeypatched, so nothing touches the network.
"""

from __future__ import annotations

import asyncio
import time

import gw_mcp.router as router
import pytest
from gw_mcp.breaker import CircuitBreaker

from tests.conftest import FakeDB, make_server


async def test_slow_upstream_times_out_at_server_timeout(monkeypatch):
    srv = make_server(slug="slow", timeout_ms=100)
    breaker = CircuitBreaker()
    monkeypatch.setattr(router, "breaker", breaker)

    async def slow_proxy(server, tool, arguments, timeout_seconds=None):
        await asyncio.sleep(5)  # would hang the call if wait_for did not cut it

    monkeypatch.setattr(router, "proxy_call", slow_proxy)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out"):
        await router.call_tool_routed(FakeDB([srv]), "slow__get_current_time", {})
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, "wait_for must cut the call near the server timeout, not proxy_call's own duration"
    assert srv.status == "Unreachable" and srv.last_error == "timeout"
    assert breaker.state_for(srv.id) == "half_open"  # 1 failure < threshold 3: degraded, not open


async def test_slow_upstream_does_not_block_a_healthy_one(monkeypatch):
    slow = make_server(slug="slow", timeout_ms=100)
    fast = make_server(slug="fast", timeout_ms=5000)
    breaker = CircuitBreaker()
    monkeypatch.setattr(router, "breaker", breaker)

    async def proxy_by_slug(server, tool, arguments, timeout_seconds=None):
        if server.slug == "slow":
            await asyncio.sleep(5)
        return {"content": [{"type": "text", "text": server.slug}], "isError": False}

    monkeypatch.setattr(router, "proxy_call", proxy_by_slug)
    db = FakeDB([slow, fast])

    started = time.monotonic()
    slow_task = asyncio.create_task(
        router.call_tool_routed(db, "slow__get_current_time", {}, timeout_seconds=0.1)
    )
    await asyncio.sleep(0.01)  # let the slow call enter its wait_for first
    fast_res = await router.call_tool_routed(db, "fast__list_notes", {})
    fast_elapsed = time.monotonic() - started

    # the healthy call completed while the slow one was still inside its wait_for
    assert fast_res["content"][0]["text"] == "fast"
    assert fast_elapsed < 0.5, "a pending slow upstream must not delay a concurrent healthy call"
    with pytest.raises(TimeoutError):
        await slow_task  # the slow call still died on its own budget, not the fast one's
    assert slow.status == "Unreachable"
    assert breaker.state_for(fast.id) == "closed", "one upstream's failure must not open another's circuit"
