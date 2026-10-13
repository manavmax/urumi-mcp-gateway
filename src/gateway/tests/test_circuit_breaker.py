"""Circuit breaker per upstream (docs/04 §6.2).

N failures open ONE upstream's circuit; success resets it; after the reset window the
circuit half-opens to allow one probe. Failure state must be isolated per server.
"""

from __future__ import annotations

import uuid

import gw_mcp.router as router
import pytest
from gw_mcp.breaker import CircuitBreaker

from tests.conftest import FakeDB, make_server


def test_breaker_opens_after_threshold_and_resets_on_success():
    b = CircuitBreaker(failure_threshold=3, reset_seconds=60)
    sid = uuid.uuid4()
    assert b.is_open(sid) is False
    for _ in range(3):
        b.record_failure(sid)
    assert b.is_open(sid) is True and b.state_for(sid) == "open"
    b.record_success(sid)
    assert b.is_open(sid) is False and b.state_for(sid) == "closed"


def test_failures_are_isolated_per_server():
    b = CircuitBreaker(failure_threshold=2)
    mine, other = uuid.uuid4(), uuid.uuid4()
    b.record_failure(mine)
    assert b.is_open(mine) is False  # below threshold: still closed
    b.record_failure(mine)
    assert b.is_open(mine) is True  # threshold reached
    assert b.is_open(other) is False  # the other server's circuit is untouched


async def test_open_circuit_rejects_before_touching_the_upstream(monkeypatch):
    srv = make_server(slug="woo")
    breaker = CircuitBreaker(failure_threshold=2)
    monkeypatch.setattr(router, "breaker", breaker)
    calls = []

    async def failing_proxy(server, tool, arguments, timeout_seconds=None):
        calls.append(server.slug)
        raise RuntimeError("upstream down")

    monkeypatch.setattr(router, "proxy_call", failing_proxy)
    db = FakeDB([srv])
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await router.call_tool_routed(db, "woo__get_order", {})
    assert breaker.is_open(srv.id) is True

    with pytest.raises(RuntimeError, match="circuit open"):
        await router.call_tool_routed(FakeDB([srv]), "woo__get_order", {})
    assert len(calls) == 2, "an open circuit must reject before the upstream is contacted"


def test_breaker_half_opens_after_the_reset_window():
    b = CircuitBreaker(failure_threshold=3, reset_seconds=60)
    sid = uuid.uuid4()
    for _ in range(3):
        b.record_failure(sid)
    assert b.is_open(sid) is True
    # wind the clock past the reset window (opened_at is in the past now)
    b._states[sid].opened_at -= 61
    assert b.is_open(sid) is False  # half-open probe allowed
    b.record_success(sid)
    assert b.state_for(sid) == "closed"
