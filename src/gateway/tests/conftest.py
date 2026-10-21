"""Shared fakes/helpers for the gateway unit tests.

No live database and no network: DB sessions are faked, upstream MCP calls are
monkeypatched. Every module under test imports its siblings as top-level names
(`from db.models import ...`), so the tests run with src/gateway as the import root.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

GW_ROOT = Path(__file__).resolve().parents[1]
if str(GW_ROOT) not in sys.path:
    sys.path.insert(0, GW_ROOT)

# uvloop is pulled in by uvicorn[standard] (a gateway runtime dep). Its event-loop
# policy raises "There is no current event loop" in asyncio.get_event_loop() instead of
# creating one on demand, which breaks pytest-asyncio's main-thread loop handling. The
# unit tests never need uvloop; reset to the default asyncio policy here. Production
# (uvicorn in the pod) is unaffected.
try:
    import uvloop  # presence check only; the policy reset below is what matters
except ImportError:
    uvloop = None  # type: ignore[assignment]

import asyncio

asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())


def sqlite_ready_metadata():
    """Prepare the shared metadata for embedded sqlite before create_all.

    sqlite cannot compile the postgres-only regex CHECK on `servers.slug` (dropped,
    as before) NOR the postgres `JSONB` type (swapped for the generic JSON type, which
    is what sqlite uses for JSON columns). Every other constraint/type stays intact, so
    the harness still tests the REAL schema. Mutating the shared metadata is fine: the
    existing CHECK-stripping already does it, and tests only ever target sqlite.
    """
    from db.models import Base
    from sqlalchemy import JSON, CheckConstraint
    from sqlalchemy.dialects.postgresql import JSONB

    for table in Base.metadata.tables.values():
        table.constraints = {c for c in table.constraints if not isinstance(c, CheckConstraint)}
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()


class FakeScalars:
    def __init__(self, item):
        self._item = item

    def first(self):
        return self._item


class FakeResult:
    def __init__(self, item):
        self._item = item

    def scalars(self):
        return self

    def first(self):
        return self._item


class FakeDB:
    """Stand-in for AsyncSession answering select(Server).where(Server.slug == X).

    The slug is read back out of the statement's whereclause (the bind parameter on the
    right-hand side), so the fakes stay honest about which server a call routes to.
    """

    def __init__(self, servers):
        self.servers = {s.slug: s for s in servers}

    async def execute(self, stmt):
        slug = None
        try:
            slug = stmt.whereclause.right.value
        except Exception:
            slug = None
        return FakeResult(self.servers.get(slug))

    async def flush(self):
        pass

    async def commit(self):
        pass


def make_server(*, slug: str, enabled: bool = True, timeout_ms: int = 500):
    return SimpleNamespace(
        id=uuid.uuid4(),
        slug=slug,
        url=f"http://{slug}.svc.cluster.local:8000/mcp",
        auth_type="none",
        header_name=None,
        credential_encrypted=None,
        enabled=enabled,
        status="Unknown",
        last_error=None,
        last_checked_at=None,
        last_ok_at=None,
        last_latency_ms=None,
        last_error_category=None,
        timeout_ms=timeout_ms,
    )


def make_user(*, role: str = "member", email: str = "user@example.com", active: bool = True):
    from db.models import User

    return User(email=email, password_hash="x", role=role, is_active=active)


# ---------------------------------------------------------------------------
# chat_loop mock-LLM harness, shared by the chat agent tests
# (test_prompt_injection, test_tool_loop_cap, test_chat_write_caveat,
# test_chat_failover_multistep). No live DB, no network: DB sessions are faked,
# upstream MCP calls are monkeypatched, the OpenAI client is a fake.

FAKE_CHAIN = ["fake-model-a", "fake-model-b"]


@pytest.fixture(autouse=True)
def reset_cooldowns():
    # cooldowns are module-level on purpose (they survive across turns); each test starts
    # from a cold chain, exactly like a restarted gateway
    import chat.llm_fallback as fb

    fb.MODEL_COOLDOWNS.clear()
    yield
    fb.MODEL_COOLDOWNS.clear()


@pytest.fixture(autouse=True)
def reset_login_throttle():
    # ADR-059: the login lockout lives in the login_failures TABLE, and every
    # test harness gets a fresh sqlite engine, so there is no module state to
    # reset anymore. The fixture stays as the seam if a future counter needs it.
    yield


def fake_settings(chain: list[str] | None = None, max_models_per_turn: int | None = None):
    """Settings double with a small deterministic model chain (default: FAKE_CHAIN)."""
    import chat.llm_fallback as fb

    models = list(chain or FAKE_CHAIN)

    class _FakeSettings:
        openai_api_key = "test-key-not-real"
        openai_base_url = None
        openai_model = models[0]
        openai_models = ",".join(models[1:])
        compact_threshold = 0  # ADR-058: auto-compact off in the shared harness

        def model_chain(self):
            return list(models)

        def max_models_per_turn(self):
            return fb.DEFAULT_MAX_MODELS_PER_TURN if max_models_per_turn is None else max_models_per_turn

    return _FakeSettings()


class ChatFakeDB:
    """Answers the server_id lookup chat_loop does for the audit row (plus commit)."""

    def __init__(self):
        self.commits = 0

    async def execute(self, stmt):
        class _Res:
            def scalar_one_or_none(self):
                return "00000000-0000-0000-0000-00000000000a"

        return _Res()

    async def commit(self):
        self.commits += 1


def allowed_tools(tools: list[dict]):
    async def _allowed(_db, _user=None):
        return tools

    return _allowed


async def noop_audit(**_kwargs):
    return None


def make_tool_call(name: str, call_id: str, signature: str | None = None):
    tc = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments="{}"))
    if signature:
        tc.extra_content = {"google": {"thought_signature": signature}}
    return tc


def tool_call_response(name: str, call_id: str = "call_1") -> SimpleNamespace:
    """OpenAI-shaped response whose message asks for ONE tool call."""
    msg = SimpleNamespace(content="", tool_calls=[make_tool_call(name, call_id)])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def text_response(text: str) -> SimpleNamespace:
    """OpenAI-shaped response that is a plain assistant answer."""
    msg = SimpleNamespace(content=text, tool_calls=[])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def fake_openai(create):
    """OpenAI client double whose chat.completions.create is the given coroutine."""

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    return _FakeOpenAI


def patch_chat_agent(monkeypatch, *, settings, tools, route, audit=noop_audit):
    """Monkeypatch chat.agent's collaborators (settings, allowed tools, tool routing,
    audit logging). Returns the agent module so the caller can import it normally."""
    import audit.queue as audit_queue
    import gw_mcp.router as gw_router
    from chat import agent

    monkeypatch.setattr(agent, "get_settings", lambda: settings)
    monkeypatch.setattr(agent, "_get_allowed_tools", allowed_tools(tools))
    monkeypatch.setattr(gw_router, "call_tool_routed", route)
    monkeypatch.setattr(audit_queue, "log_audit", audit)
    return agent


def install_fake_openai(monkeypatch, create):
    """Swap openai.AsyncOpenAI for a fake that calls `create` on every completion."""
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", fake_openai(create))


def chat_user(user_id: str = "00000000-0000-0000-0000-000000000001"):
    return SimpleNamespace(id=user_id)


async def run_chat_turn(monkeypatch, db, user, *, settings, tools, route, create,
                        messages, request_id: str, audit=noop_audit) -> list[dict]:
    """Full harness turn: patch agent + client, drive chat_loop, return its SSE events."""
    agent = patch_chat_agent(monkeypatch, settings=settings, tools=tools, route=route, audit=audit)
    install_fake_openai(monkeypatch, create)
    events: list[dict] = []
    async for evt in agent.chat_loop(db, user, messages, request_id):
        events.append(evt)
    return events
