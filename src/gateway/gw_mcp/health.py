"""Background health loop (docs/02 §3.4, 04 lifespan, docs/11_OBSERVABILITY).

Probes every enabled server with a lightweight tools/list and updates servers.status
plus the health-tracking columns (last_checked_at, last_ok_at, last_latency_ms,
last_error_category). Passive detection: an upstream call or tools/list that fails with
a connection-level error marks the server Unreachable immediately (see aggregator.py and
router.py) - no waiting for this loop. Interval is a Helm value, default 5 seconds, and
each check has a 2 second timeout. While Unreachable the loop still runs, so recovery
flips the status back within ~one interval of the pod returning.
"""

from __future__ import annotations

import asyncio
import logging
import time

from config import get_settings
from db.models import Server
from db.session import get_session_factory
from sqlalchemy import select

from gw_mcp.aggregator import fetch_and_cache_tools
from gw_mcp.categorize import classify
from gw_mcp.health_state import record_failure, record_success

logger = logging.getLogger("gateway.health")


async def probe_once():
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as db:
        res = await db.execute(select(Server).where(Server.enabled.is_(True)))
        servers = list(res.scalars().all())
        from gw_mcp.metrics import set_upstream_up

        for s in servers:
            started = time.monotonic()
            try:
                await asyncio.wait_for(
                    fetch_and_cache_tools(db, s, timeout_seconds=settings.health_timeout_seconds),
                    timeout=settings.health_timeout_seconds + 2,
                )
                record_success(s, latency_ms=int((time.monotonic() - started) * 1000))
                set_upstream_up(s.slug, s.status == "Connected")
                logger.debug("health ok %s", s.slug)
            except Exception as exc:
                record_failure(s, classify(exc), latency_ms=int((time.monotonic() - started) * 1000))
                set_upstream_up(s.slug, False)
                logger.warning("health fail %s category=%s", s.slug, s.last_error_category)
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
