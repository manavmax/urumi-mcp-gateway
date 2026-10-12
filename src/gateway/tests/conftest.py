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
