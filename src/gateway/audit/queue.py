"""Async audit queue + batch writer (docs/04 §7).

Never blocks tool call: put_nowait, drop with log if full.
Worker flushes every 1s or 100 items.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import AuditLog

logger = logging.getLogger("gateway.audit")

audit_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)


async def log_audit(
    *,
    user_id: uuid.UUID | None,
    api_key_id: uuid.UUID | None,
    server_id: uuid.UUID | None,
    server_slug: str,
    tool_exposed_name: str,
    tool_upstream_name: str,
    request_id: uuid.UUID,
    duration_ms: int,
    outcome: str,
    error_code: str | None = None,
    client_ip: str | None = None,
):
    item = dict(
        user_id=user_id,
        api_key_id=api_key_id,
        server_id=server_id,
        server_slug=server_slug,
        tool_exposed_name=tool_exposed_name,
        tool_upstream_name=tool_upstream_name,
        request_id=request_id,
        duration_ms=duration_ms,
        outcome=outcome,
        error_code=error_code,
        client_ip=client_ip,
        ts=datetime.now(timezone.utc),
    )
    try:
        audit_queue.put_nowait(item)
    except asyncio.QueueFull:
        logger.error("audit queue full, dropping audit for %s %s", server_slug, tool_exposed_name)


async def audit_worker():
    settings = get_settings()
    batch: list[dict] = []
    batch_size = settings.audit_batch_size
    flush_interval = settings.audit_flush_interval_seconds
    logger.info("audit worker started batch=%s interval=%s", batch_size, flush_interval)
    # lazy import to avoid circular
    from db.session import get_session_factory

    factory = get_session_factory()

    async def flush(items: list[dict]):
        if not items:
            return
        try:
            async with factory() as db:
                for it in items:
                    log = AuditLog(
                        ts=it["ts"],
                        user_id=it["user_id"],
                        api_key_id=it["api_key_id"],
                        server_id=it["server_id"],
                        server_slug=it["server_slug"],
                        tool_exposed_name=it["tool_exposed_name"],
                        tool_upstream_name=it["tool_upstream_name"],
                        request_id=it["request_id"],
                        duration_ms=it["duration_ms"],
                        outcome=it["outcome"],
                        error_code=it.get("error_code"),
                        client_ip=it.get("client_ip"),
                    )
                    db.add(log)
                await db.commit()
                logger.debug("audit flushed %s", len(items))
        except Exception as exc:
            logger.exception("audit flush failed: %s", exc)

    while True:
        try:
            try:
                item = await asyncio.wait_for(audit_queue.get(), timeout=flush_interval)
                batch.append(item)
                # drain without waiting if more queued
                while len(batch) < batch_size:
                    try:
                        batch.append(audit_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                if len(batch) >= batch_size:
                    to_flush = batch
                    batch = []
                    await flush(to_flush)
            except asyncio.TimeoutError:
                if batch:
                    to_flush = batch
                    batch = []
                    await flush(to_flush)
        except asyncio.CancelledError:
            if batch:
                await flush(batch)
            logger.info("audit worker cancelled")
            break
        except Exception as exc:
            logger.exception("audit worker loop error: %s", exc)
