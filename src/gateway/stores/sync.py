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

from db.models import LEGACY_TIMEOUT_MS, Server, Store
from sqlalchemy import select

logger = logging.getLogger("gateway.stores")


def _reassert_call_default(server: Server) -> None:
    """Sync-owned (internal) upstreams follow the global call default (ADR-089).

    A row registered before the timeout cleanup carries a hard 5000; re-assert
    the sentinel on every sync so it self-heals to the global call default.
    Non-internal rows (admin-created servers) are never touched.
    """
    if server.internal and server.timeout_ms != LEGACY_TIMEOUT_MS:
        server.timeout_ms = LEGACY_TIMEOUT_MS


async def register_store_upstream(db, store: Store) -> None:
    """Idempotent: an existing registration for the slug is reused."""

    existing = (await db.execute(select(Server).where(Server.slug == store.slug))).scalars().first()
    url = f"http://{store.slug}-woo-mcp.{store.namespace}.svc:8000/mcp"
    if existing:
        if existing.url != url:
            existing.url = url
        existing.enabled = True
        existing.internal = True
        _reassert_call_default(existing)
        return
    db.add(Server(
        slug=store.slug,
        url=url,
        auth_type="none",
        timeout_ms=LEGACY_TIMEOUT_MS,  # sentinel: follows the global call default (ADR-089)
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
        # self-heal: a Ready store's registration is written once (at the
        # Provisioning -> Ready transition), so rows carrying the pre-ADR-089
        # hard 5000 would never be revisited. Re-assert the global call default
        # on sync-owned rows every pass (timeout only: never url/enabled, so an
        # admin-disabled upstream stays disabled). The hosted path already
        # re-asserts via its Ready self-heal.
        ready = (await db.execute(select(Store).where(Store.status == "Ready"))).scalars().all()
        for store in ready:
            srv = (await db.execute(select(Server).where(Server.slug == store.slug))).scalars().first()
            if srv:
                _reassert_call_default(srv)
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
        try:
            if settings.hosted_enabled:
                await sync_hosted_once()
        except Exception as exc:
            logger.warning("hosted sync pass failed: %s", exc)
        await sleep(settings.stores_sync_interval_seconds)


# ---- Phase 6 (ADR-062): hosted server sync ----------------------------------

async def register_hosted_upstream(db, hosted) -> None:
    """Idempotent: register the hosted server's MCP endpoint as an INTERNAL
    upstream (slug = name, URL http://<name>.hosted-<name>.svc:<port>)."""
    existing = (await db.execute(select(Server).where(Server.slug == hosted.name))).scalars().first()
    url = f"http://{hosted.name}.hosted-{hosted.name}.svc:{hosted.port}/mcp"
    if existing:
        if existing.url != url:
            existing.url = url
        existing.enabled = True
        existing.internal = True
        _reassert_call_default(existing)
        return
    db.add(Server(
        slug=hosted.name,
        url=url,
        auth_type="none",
        timeout_ms=LEGACY_TIMEOUT_MS,  # sentinel: follows the global call default (ADR-089)
        enabled=True,
        internal=True,
        status="Unknown",
    ))
    logger.info("registered internal upstream for hosted %s at %s", hosted.name, url)


async def remove_hosted_upstream(db, hosted) -> None:
    existing = (await db.execute(select(Server).where(Server.slug == hosted.name))).scalars().first()
    if existing:
        if not existing.internal:
            logger.warning("hosted %s slug collides with a non-internal server; not removing", hosted.name)
            return
        await db.delete(existing)
        logger.info("removed internal upstream for hosted %s", hosted.name)


async def sync_hosted_once() -> None:
    """Advance HostedServer rows like the store sync does:
    Provisioning -> Ready (register upstream) / Failed (safe reason);
    Deleting -> namespace gone -> remove upstream + row."""
    from config import get_settings

    settings = get_settings()
    from db.models import HostedServer
    from db.session import get_session_factory

    from stores.client import hosted_state

    def _age_seconds(created_at) -> float:
        if created_at is None:
            return 0.0
        from datetime import UTC, datetime

        dt = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
        return (datetime.now(UTC) - dt).total_seconds()

    factory = get_session_factory()
    async with factory() as db:
        in_flight = (
            await db.execute(select(HostedServer).where(HostedServer.status.in_(("Provisioning", "Deleting", "Ready"))))
        ).scalars().all()
        for hosted in in_flight:
            if hosted.status == "Ready":
                # self-heal: re-assert the upstream registration (a URL pattern
                # fix or a missed transition must not strand a stale row)
                await register_hosted_upstream(db, hosted)
                continue
            state = await hosted_state(hosted.name)
            if state is None:
                continue  # provisioner unreachable: retry next pass
            phase = state.get("phase")
            reason = state.get("reason") or ""
            if hosted.status == "Provisioning":
                if phase == "ready":
                    await register_hosted_upstream(db, hosted)
                    hosted.status = "Ready"
                    hosted.failure_reason = None
                    logger.info("hosted %s is Ready", hosted.name)
                elif phase == "gone":
                    # a Provisioning hosted server whose namespace vanished:
                    # either the budget expired on the provisioner side or the
                    # apply never landed - mark Failed with the budget reason
                    if _age_seconds(hosted.created_at) > settings.hosted_timeout_seconds:
                        hosted.status = "Failed"
                        hosted.failure_reason = reason or f"not ready after {settings.hosted_timeout_seconds}s"
                        logger.warning("hosted %s failed: %s", hosted.name, hosted.failure_reason)
                    # else: the apply may still be in flight (or queued) - wait
                elif phase == "provisioning":
                    if _age_seconds(hosted.created_at) > settings.hosted_timeout_seconds:
                        hosted.status = "Failed"
                        hosted.failure_reason = f"not ready after {settings.hosted_timeout_seconds}s"
                        logger.warning("hosted %s failed: %s", hosted.name, hosted.failure_reason)
            elif hosted.status == "Deleting" and phase == "gone":
                await remove_hosted_upstream(db, hosted)
                await db.delete(hosted)
                logger.info("hosted %s teardown complete; row removed", hosted.name)
        await db.commit()
