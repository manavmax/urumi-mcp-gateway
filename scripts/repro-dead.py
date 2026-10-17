import asyncio
import types

from db.models import Server
from db.session import get_session_factory
from gw_mcp.aggregator import fetch_and_cache_tools
from sqlalchemy import select

seen = set()


def dump(e, depth=0, via=""):
    if e is None:
        return
    if id(e) in seen:
        print(f"{'  ' * depth}(cycle {type(e).__name__})")
        return
    seen.add(id(e))
    pad = "  " * depth
    print(f"{pad}{via} {type(e).__module__}.{type(e).__name__} errno={getattr(e,'errno',None)} msg={str(e)[:120]}")
    grp = getattr(e, "exceptions", None)
    if isinstance(grp, (list, tuple)):
        for sub in grp:
            dump(sub, depth + 1, "[group]")
    c = e.__cause__
    if c:
        dump(c, depth + 1, "[cause]")
    c = e.__context__
    if c:
        dump(c, depth + 1, "[ctx]")


async def main():
    async with get_session_factory() as db:
        (await db.execute(select(Server))).scalars().all()
    for label, url in [
        ("no-such-svc (dns)", "http://urumi-no-such-svc:8000/mcp"),
    ]:
        seen.clear()
        dead = types.SimpleNamespace(
            slug="dead", url=url, auth_type="none", header_name=None,
            credential_encrypted=None, timeout_ms=2000,
        )
        print(f"########## {label} ##########")
        try:
            await fetch_and_cache_tools(db, dead, timeout_seconds=2)
        except Exception as exc:
            dump(exc)


asyncio.run(main())
