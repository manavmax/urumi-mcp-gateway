"""Background health loop (docs/02 §3.4, 04 lifespan).

Probes every enabled server with a lightweight tools/list and updates servers.status.
"""

from __future__ import annotations

import asyncio
import logging

from config import get_settings
from db.models import Server
from db.session import get_session_factory
from sqlalchemy import select

from gw_mcp.aggregator import fetch_and_cache_tools

logger = logging.getLogger("gateway.health")


async def probe_once():
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as db:
        res = await db.execute(select(Server).where(Server.enabled.is_(True)))
        servers = list(res.scalars().all())
        for s in servers:
            try:
                await asyncio.wait_for(
                    fetch_and_cache_tools(db, s, timeout_seconds=settings.health_timeout_seconds),
                    timeout=settings.health_timeout_seconds + 2,
                )
                s.status = "Connected"
                s.last_error = None
                logger.debug("health ok %s", s.slug)
            except Exception as exc:
                s.status = "Unreachable"
                s.last_error = str(exc)[:500]
                logger.warning("health fail %s: %s", s.slug, exc)
        try:
            await db.commit()
        except Exception:
            await db.rollback()


async def health_loop():
    settings = get_settings()
    interval = settings.health_interval_seconds
    logger.info("health loop started interval=%ss", interval)
    while True:
        try:
            await probe_once()
        except asyncio.CancelledError:
            logger.info("health loop cancelled")
            break
        except Exception as exc:
            logger.exception("health loop error: %s", exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
