"""Store sync loop (Phase 5, ADR-060).

Runs in the gateway's background: polls the provisioner for stores in
Provisioning/Deleting and advances the DB rows:
  Provisioning -> Ready    + register the store's woo-mcp as an INTERNAL server
                           (slug = store slug, so tools are <slug>__list_orders)
  Provisioning -> Failed   (safe reason from the provisioner, e.g. timeout)
  Deleting    -> row gone + remove the internal server registration

The registration uses the SAME Server row shape the health loop already
serves, so tool discovery, permissions, rate limits and audit work unchanged.
WooCommerce keys never pass through the gateway: they live in the store
namespace and only that store's woo-mcp reads them.
"""

from __future__ import annotations

import logging

from db.models import Server, Store
from sqlalchemy import select

logger = logging.getLogger("gateway.stores")


async def register_store_upstream(db, store: Store) -> None:
    """Idempotent: an existing registration for the slug is reused."""

    existing = (await db.execute(select(Server).where(Server.slug == store.slug))).scalars().first()
    url = f"http://{store.slug}-woo-mcp.{store.namespace}.svc:8000/mcp"
    if existing:
        if existing.url != url:
            existing.url = url
        existing.enabled = True
        existing.internal = True
        return
    db.add(Server(
        slug=store.slug,
        url=url,
        auth_type="none",
        timeout_ms=5000,
        enabled=True,
        internal=True,
        status="Unknown",
    ))
    logger.info("registered internal upstream for store %s at %s", store.slug, url)


async def remove_store_upstream(db, store: Store) -> None:
    existing = (await db.execute(select(Server).where(Server.slug == store.slug))).scalars().first()
    if existing:
        if not existing.internal:
            # a same-slug NON-internal server appeared somehow: leave it alone
            logger.warning("store %s slug collides with a non-internal server; not removing", store.slug)
            return
        await db.delete(existing)
        logger.info("removed internal upstream for store %s", store.slug)


async def sync_once() -> None:
    from db.session import get_session_factory

    from stores.client import store_state

    factory = get_session_factory()
    async with factory() as db:
        in_flight = (
            await db.execute(select(Store).where(Store.status.in_(("Provisioning", "Deleting"))))
        ).scalars().all()
        for store in in_flight:
            state = await store_state(store.slug)
            if state is None:
                # provisioner unreachable: retry next pass
                continue
            phase = state.get("phase")
            reason = state.get("reason") or ""
            if store.status == "Provisioning":
                if phase == "ready":
                    await register_store_upstream(db, store)
                    store.status = "Ready"
                    store.failure_reason = None
                    logger.info("store %s is Ready", store.slug)
                elif phase == "failed":
                    store.status = "Failed"
                    store.failure_reason = reason or "provisioning failed"
                    logger.warning("store %s failed: %s", store.slug, store.failure_reason)
                elif phase == "gone":
                    store.status = "Failed"
                    store.failure_reason = "the provisioner lost the store namespace"
            elif store.status == "Deleting" and phase == "gone":
                await remove_store_upstream(db, store)
                await db.delete(store)
                logger.info("store %s teardown complete; row removed", store.slug)
        await db.commit()


async def sync_loop() -> None:
    from asyncio import sleep

    from config import get_settings

    settings = get_settings()
    if not settings.stores_enabled:
        logger.info("store sync loop disabled (stores off)")
        return
    logger.info("store sync loop started (interval %ss)", settings.stores_sync_interval_seconds)
    while True:
        try:
            await sync_once()
        except Exception as exc:
            logger.warning("store sync pass failed: %s", exc)
        await sleep(settings.stores_sync_interval_seconds)
