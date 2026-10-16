"""Per-role tool permissions — the ONE enforcement core (ADR-033).

Used by both the external MCP endpoint (/mcp, /api/tools) and the chat agent, so
listing and calling can never disagree:

  - tools/list  (and /api/tools, and the chat agent's tool load) calls
    `deny_rules_for_role` -> `tool_denied` to FILTER OUT denied tools.
  - tools/call  calls `assert_call_allowed` (which uses the same `tool_denied`
    predicate on the same live deny set) BEFORE routing upstream.

Rules live in the `tool_permissions` table (role, server_slug, tool_name). Only
role='member' is stored today; admins always have all tools. A rule with
tool_name=None denies the whole server. Rules are read LIVE on every call: a
policy change takes effect on the very next call, and removing a rule restores
the tool (no cache that could survive a change).

Default policy = allow everything. An empty table changes nothing.
"""

from __future__ import annotations

from db.models import ToolPermission
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

DENIED_ROLE = "member"

# Sentinel for a whole-server deny rule inside the deny set: 'woo__*'
SERVER_WILD = "__*"


async def deny_rules_for_role(db: AsyncSession, role: str) -> frozenset[str]:
    """Live read of every deny rule for a role, as a set of denied EXPOSED names.

    A whole-server rule (tool_name NULL) becomes a '<slug>__*' sentinel; an explicit
    rule stores the exposed name ('woo__create_product'). 'admin' is never denied.
    No caching survives a change: every call and every list reads the table.
    """
    if role != DENIED_ROLE:
        return frozenset()
    res = await db.execute(select(ToolPermission).where(ToolPermission.role == role))
    rows = res.scalars().all()
    names: set[str] = set()
    for r in rows:
        if r.tool_name is None:
            names.add(f"{r.server_slug}{SERVER_WILD}")
        else:
            names.add(r.tool_name)
    return frozenset(names)


def tool_denied(deny: frozenset[str], exposed_name: str) -> bool:
    """THE single deny predicate: is this exposed tool denied?

    A whole-server deny (a '<slug>__*') denies every tool of that server; an explicit
    exposed name denies exactly that tool. Both the listing filter and the call check
    use THIS function — there is exactly one enforcement function.
    """
    if not deny:
        return False
    if exposed_name in deny:
        return True
    slug = exposed_name.split("__", 1)[0] if "__" in exposed_name else exposed_name
    return f"{slug}{SERVER_WILD}" in deny


async def filter_tools_for_user(db: AsyncSession, user, tools: list[dict]) -> list[dict]:
    """(a) tools/list: filter OUT denied tools for the user's role. Admins always see all."""
    if user is None or getattr(user, "role", None) == "admin":
        return tools
    deny = await deny_rules_for_role(db, getattr(user, "role", ""))
    if not deny:
        return tools
    return [t for t in tools if not tool_denied(deny, t.get("name", ""))]


async def assert_call_allowed(db: AsyncSession, user, exposed_name: str) -> None:
    """(b) tools/call: reject a denied tool BEFORE routing upstream.

    Raises PermissionError when the user's role denies this exposed name. The error is
    the standard unknown-tool error the gateway already returns for a tool the caller
    could not list — the caller learns nothing about whether the tool exists beyond
    that (no existence leak).
    """
    if user is None or getattr(user, "role", None) == "admin":
        return
    deny = await deny_rules_for_role(db, getattr(user, "role", ""))
    if tool_denied(deny, exposed_name):
        raise PermissionError(f"unknown tool: {exposed_name}")


async def list_deny_rules(db: AsyncSession) -> list[ToolPermission]:
    """All deny rules (admin API/UI only)."""
    res = await db.execute(select(ToolPermission).order_by(ToolPermission.server_slug, ToolPermission.tool_name))
    return list(res.scalars().all())


def rule_covers(rule: ToolPermission, exposed_name: str) -> bool:
    """Does one rule deny this exposed name? Used by the admin UI to mark restricted tools."""
    if rule.tool_name is None:
        return exposed_name.split("__", 1)[0] == rule.server_slug
    return rule.tool_name == exposed_name
