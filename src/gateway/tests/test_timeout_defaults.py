"""Per-upstream timeouts match the brief (ADR-089): list ~3s, call ~15s.

The global defaults live in config (Helm gateway.timeouts.listSeconds/callSeconds
-> LIST_TIMEOUT_SECONDS / CALL_TIMEOUT_SECONDS). A stored servers.timeout_ms that
equals the legacy column default 10000 (db.models.LEGACY_TIMEOUT_MS) - which every
pre-existing row and every seeded internal server carries - means "follow the
global call default"; an explicit admin value still wins.

The cut-offs tested here are the REAL asyncio.wait_for layers in
gw_mcp.aggregator (list) and gw_mcp.router (call); only the network-facing
coroutine is mocked, and the settings values are patched small so tests stay fast.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import config
import gw_mcp.aggregator as aggregator
import gw_mcp.router as router
import pytest
from config import Settings
from db.models import LEGACY_TIMEOUT_MS, Server
from gw_mcp.breaker import CircuitBreaker

from tests.conftest import FakeDB, make_server

# ---------------------------------------------------------------- resolution

def test_effective_call_timeout_uses_global_for_the_legacy_sentinel():
    srv = SimpleNamespace(timeout_ms=LEGACY_TIMEOUT_MS)  # every existing row / seed
    assert router.effective_call_timeout_seconds(srv, SimpleNamespace(call_timeout_seconds=15)) == 15.0
    # 0 / missing behaves the same (never a zero-second call)
    assert router.effective_call_timeout_seconds(SimpleNamespace(timeout_ms=0), SimpleNamespace(call_timeout_seconds=15)) == 15.0


def test_effective_call_timeout_keeps_explicit_per_server_value():
    assert router.effective_call_timeout_seconds(SimpleNamespace(timeout_ms=5000), SimpleNamespace(call_timeout_seconds=15)) == 5.0
    assert router.effective_call_timeout_seconds(SimpleNamespace(timeout_ms=1001), SimpleNamespace(call_timeout_seconds=15)) == 1.001


def test_default_settings_match_the_brief():
    s = Settings()
    assert s.list_timeout_seconds == 3
    assert s.call_timeout_seconds == 15
    assert not hasattr(s, "default_timeout_ms"), "the old 10000ms knob must be gone"


def test_settings_read_helm_env(monkeypatch):
    monkeypatch.delenv("LIST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("CALL_TIMEOUT_SECONDS", raising=False)
    assert Settings().list_timeout_seconds == 3
    assert Settings().call_timeout_seconds == 15
    monkeypatch.setenv("LIST_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("CALL_TIMEOUT_SECONDS", "20")
    assert Settings().list_timeout_seconds == 4
    assert Settings().call_timeout_seconds == 20


def test_column_and_seed_use_the_sentinel():
    """New rows (SQLAlchemy column default) and the seeded internal servers all
    store 10000, which the resolver maps to the global call default."""
    assert Server.__table__.columns["timeout_ms"].default.arg == LEGACY_TIMEOUT_MS == 10000


async def test_seed_default_servers_write_the_sentinel():
    """seed_default_servers (woo/time/notes) stores the sentinel, so the seeded
    internal upstreams follow the global call default (15s, ADR-089)."""
    from registry.crud import seed_default_servers

    class SeedDB:
        def __init__(self):
            self.added: list = []

        async def execute(self, stmt):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))

        def add(self, row):
            self.added.append(row)

        async def flush(self):
            pass

    db = SeedDB()
    await seed_default_servers(db)
    slugs = {s.slug: s.timeout_ms for s in db.added}
    assert set(slugs) >= {"woo", "time", "notes"}, slugs
    assert set(slugs.values()) == {LEGACY_TIMEOUT_MS}, slugs


# ---------------------------------------------------------------- call timeout

async def test_hanging_call_is_cut_at_the_global_call_timeout(monkeypatch):
    """A hanging upstream is cut off near call_timeout_seconds: the server row
    carries only the legacy 10000 sentinel, so the global default applies, and
    the error names the upstream."""
    srv = make_server(slug="slow", timeout_ms=LEGACY_TIMEOUT_MS)
    breaker = CircuitBreaker()
    monkeypatch.setattr(router, "breaker", breaker)
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(call_timeout_seconds=0.2))

    async def hanging_proxy(server, tool, arguments, timeout_seconds=None):
        await asyncio.sleep(30)  # would hang the test if wait_for did not cut it

    monkeypatch.setattr(router, "proxy_call", hanging_proxy)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="Upstream slow timed out"):
        await router.call_tool_routed(FakeDB([srv]), "slow__get_current_time", {})
    elapsed = time.monotonic() - started
    assert elapsed < 3.0, f"call must be cut near the global default (+1s grace), took {elapsed:.2f}s"
    assert srv.status == "Unreachable" and srv.last_error == "timeout"


# ---------------------------------------------------------------- list timeout

class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _CacheAwareDB:
    """Minimal AsyncSession stand-in for the fan-out: the tools upsert finds no
    existing rows; the stale-cache read (Tool.server_id.in_(...)) returns one
    cached row, so the real fanout + fallback code runs end to end."""

    is_active = True

    def __init__(self):
        self.cached: list = []

    def add(self, row):
        pass

    async def flush(self):
        pass

    async def rollback(self):
        pass

    async def execute(self, stmt):
        # compiled SQL: the cache read carries "server_id IN (...)", the upsert
        # select carries "server_id = :..."
        if " in (" in str(stmt).lower():
            return _Scalars(self.cached[:])
        return _Scalars([])


async def test_hanging_list_is_cut_at_the_list_timeout_and_others_list(monkeypatch):
    """One hanging upstream is cut off at the list timeout (its tools still come
    from the stale cache), a healthy upstream lists normally and is NOT delayed
    by the hanging one, and the warnings make the failure clear."""
    slow = make_server(slug="slow", timeout_ms=LEGACY_TIMEOUT_MS)
    fast = make_server(slug="fast", timeout_ms=LEGACY_TIMEOUT_MS)
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(list_timeout_seconds=0.2, allowed_host_suffix_list=lambda: []))

    async def fetch_by_slug(server, timeout_seconds):
        # the REAL fetch_and_cache_tools still wraps this in wait_for(timeout+2)
        if server.slug == "slow":
            await asyncio.sleep(30)  # would hang the list if wait_for did not cut it
        return [{"name": "ping", "description": "ping", "inputSchema": {"type": "object", "properties": {}}}]

    monkeypatch.setattr(aggregator, "_fetch_tools_for_server", fetch_by_slug)

    # one cached row for the slow server: the stale-cache fallback must serve it
    cached_row = SimpleNamespace(server_id=slow.id, upstream_name="stale_tool",
                                 exposed_name="slow__stale_tool", description="[slow] stale_tool",
                                 input_schema={"type": "object", "properties": {}})

    db = _CacheAwareDB()
    db.cached = [cached_row]
    started = time.monotonic()
    tools, warnings = await aggregator.fanout_list_tools(db, [slow, fast])
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, f"the hanging upstream must be cut near its own budget, took {elapsed:.2f}s"
    # the healthy upstream contributed its tools, untouched by the hanging one
    assert any(t["name"] == "fast__ping" for t in tools), tools
    # the slow one was cut at the list timeout and its stale cache served instead
    stale = [w for w in warnings if w.get("server") == "slow" and w.get("stale_cache")]
    assert stale, warnings
    assert any(t["name"] == "slow__stale_tool" for t in tools), tools


async def test_hanging_list_reports_a_clear_error_without_cache(monkeypatch):
    """With no cached rows the cut-off surfaces as a plain warning naming the
    upstream and the timeout - no phantom tools, no lost fast server."""
    slow = make_server(slug="slow", timeout_ms=LEGACY_TIMEOUT_MS)
    fast = make_server(slug="fast", timeout_ms=LEGACY_TIMEOUT_MS)
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(list_timeout_seconds=0.2, allowed_host_suffix_list=lambda: []))

    async def fetch_by_slug(server, timeout_seconds):
        if server.slug == "slow":
            await asyncio.sleep(30)
        return [{"name": "ping", "description": "ping", "inputSchema": {"type": "object", "properties": {}}}]

    monkeypatch.setattr(aggregator, "_fetch_tools_for_server", fetch_by_slug)

    class NoCacheDB(_CacheAwareDB):
        async def execute(self, stmt):
            return _Scalars([])  # cache read finds nothing either

    started = time.monotonic()
    tools, warnings = await aggregator.fanout_list_tools(NoCacheDB(), [slow, fast])
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, f"cut near the list budget, took {elapsed:.2f}s"
    assert any(t["name"] == "fast__ping" for t in tools), tools
    assert not any(t["name"].startswith("slow__") for t in tools), tools
    slow_warn = [w for w in warnings if w.get("server") == "slow"]
    assert slow_warn and "timeout" in slow_warn[0]["error"].lower(), warnings
    assert not any(w.get("stale_cache") for w in warnings), warnings
