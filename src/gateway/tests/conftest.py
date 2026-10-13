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
        timeout_ms=timeout_ms,
    )


def make_user(*, role: str = "member", email: str = "user@example.com", active: bool = True):
    from db.models import User

    return User(email=email, password_hash="x", role=role, is_active=active)
