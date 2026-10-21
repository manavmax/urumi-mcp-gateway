"""Stores API (Phase 5, ADR-060): list/create/delete per-user storefronts.

The GATEWAY owns authorization and quotas (per-user max, global max) and then
calls the provisioner; the provisioner owns the cluster. The gateway's sync
loop (main.py) moves rows Provisioning -> Ready (registering the store's
woo-mcp upstream as an internal server) and Deleting -> gone.

Members see and manage only their own stores, up to stores.maxPerUser; admins
see and can manage all. Nothing here handles credentials: the WooCommerce keys
are generated INSIDE the store namespace and never reach the gateway.
"""

from __future__ import annotations

import logging
import uuid

from audit.admin_events import record_admin_event
from auth.rbac import get_current_user_via_session, verify_csrf
from db.models import Server, Store, User
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("gateway.stores")

router = APIRouter()

RESERVED_SLUGS_GATEWAY = {
    "woo", "gateway", "dashboard", "postgres", "mariadb", "wordpress",
    "demo-time", "demo-notes", "urumi", "admin", "api", "auth", "www", "mail",
    "store", "stores", "provisioner", "internal", "gateway-admin",
}


def _slugify(display_name: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9-]+", "-", (display_name or "").strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:30].rstrip("-")
    return slug


def _validate_slug(slug: str) -> str:
    import re

    if not slug or len(slug) > 30 or not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", slug):
        raise HTTPException(status_code=400, detail="store name must yield 1-30 chars of lowercase letters, digits and hyphens")
    if "--" in slug:
        raise HTTPException(status_code=400, detail="store name must not contain consecutive hyphens")
    if slug.startswith("store-"):
        raise HTTPException(status_code=400, detail="the 'store-' prefix is reserved")
    if slug in RESERVED_SLUGS_GATEWAY:
        raise HTTPException(status_code=400, detail="that store name is reserved")
    return slug


def _store_out(s: Store, *, is_admin: bool, owner_email: str | None = None) -> dict:
    out = {
        "id": str(s.id),
        "slug": s.slug,
        "display_name": s.display_name,
        "namespace": s.namespace,
        "status": s.status,
        "failure_reason": s.failure_reason,
        "url": s.url,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }
    if is_admin:
        out["owner_user_id"] = str(s.owner_user_id)
        out["owner_email"] = owner_email
    return out


def _require_stores_enabled() -> None:
    from config import get_settings

    if not get_settings().stores_enabled:
        raise HTTPException(status_code=403, detail="store provisioning is disabled on this gateway")


@router.get("/api/stores")
async def list_stores(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    _require_stores_enabled()
    if user.role == "admin":
        rows = (await db.execute(select(Store).order_by(Store.created_at.desc()))).scalars().all()
        owners = {u.id: u.email for u in (await db.execute(select(User))).scalars().all()}
        return {"stores": [_store_out(s, is_admin=True, owner_email=owners.get(s.owner_user_id)) for s in rows]}
    rows = (
        await db.execute(select(Store).where(Store.owner_user_id == user.id).order_by(Store.created_at.desc()))
    ).scalars().all()
    return {"stores": [_store_out(s, is_admin=False) for s in rows]}


@router.post("/api/stores", status_code=201)
async def create_store(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    _require_stores_enabled()
    verify_csrf(request)
    body = await request.json()
    display_name = str(body.get("display_name") or "").strip()[:60]
    if not display_name:
        raise HTTPException(status_code=400, detail="store name is required")
    slug = _validate_slug(_slugify(display_name))

    from config import get_settings

    settings = get_settings()

    # quotas: per-user and global (admins are exempt from the per-user cap -
    # they manage the platform - but never from the global one)
    mine = (await db.execute(select(func.count()).select_from(Store).where(Store.owner_user_id == user.id))).scalar() or 0
    if user.role != "admin" and mine >= settings.stores_max_per_user:
        raise HTTPException(
            status_code=400,
            detail=f"you already have {mine} stores (maximum {settings.stores_max_per_user}); delete one first",
        )
    total = (await db.execute(select(func.count()).select_from(Store))).scalar() or 0
    if total >= settings.stores_global_max:
        raise HTTPException(status_code=400, detail=f"the platform store limit is reached ({settings.stores_global_max})")

    # slug uniqueness: neither another store, nor a registered server slug
    # (server tools and store tools share the <slug>__ prefix namespace)
    clash = (await db.execute(select(Store).where(Store.slug == slug))).scalars().first()
    if clash:
        raise HTTPException(status_code=400, detail="a store with that name already exists")
    srv_clash = (await db.execute(select(Server).where(Server.slug == slug))).scalars().first()
    if srv_clash:
        raise HTTPException(status_code=400, detail="that name collides with a registered server slug")

    store = Store(
        owner_user_id=user.id,
        slug=slug,
        display_name=display_name,
        namespace=f"store-{slug}",
        status="Provisioning",
        url=f"http://{slug}.{settings.stores_base_domain}",
    )
    db.add(store)
    await db.flush()

    from stores.client import provision_store

    try:
        await provision_store(slug)
    except Exception as exc:
        store.status = "Failed"
        store.failure_reason = str(exc)[:300]
        await db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    record_admin_event(
        db,
        actor_user_id=user.id,
        action="store.create",
        target_type="store",
        target_ref=slug,
        details={"store_id": str(store.id), "namespace": store.namespace},
    )
    await db.commit()
    return _store_out(store, is_admin=user.role == "admin")


@router.delete("/api/stores/{store_id}", status_code=200)
async def delete_store(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    _require_stores_enabled()
    verify_csrf(request)
    store = (await db.execute(select(Store).where(Store.id == store_id))).scalars().first()
    if not store:
        raise HTTPException(status_code=404, detail="store not found")
    if store.owner_user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="not your store")
    if store.status == "Deleting":
        return {"id": str(store.id), "status": "Deleting"}

    store.status = "Deleting"
    store.failure_reason = None

    from stores.client import deprovision_store

    try:
        await deprovision_store(store.slug)
    except Exception as exc:
        # keep the row in Deleting anyway: the sync loop re-attempts teardown
        logger.warning("deprovision call failed for %s: %s", store.slug, exc)

    record_admin_event(
        db,
        actor_user_id=user.id,
        action="store.delete",
        target_type="store",
        target_ref=store.slug,
        details={"store_id": str(store.id), "namespace": store.namespace},
    )
    await db.commit()
    return {"id": str(store.id), "status": "Deleting"}


@router.post("/api/stores/{store_id}/retry", status_code=200)
async def retry_store(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    """Retry a Failed store: re-run provisioning (idempotent helm)."""
    _require_stores_enabled()
    verify_csrf(request)
    store = (await db.execute(select(Store).where(Store.id == store_id))).scalars().first()
    if not store:
        raise HTTPException(status_code=404, detail="store not found")
    if store.owner_user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="not your store")
    if store.status not in ("Failed",):
        raise HTTPException(status_code=400, detail="only a Failed store can be retried")

    from stores.client import provision_store

    store.status = "Provisioning"
    store.failure_reason = None
    try:
        await provision_store(store.slug)
    except Exception as exc:
        store.status = "Failed"
        store.failure_reason = str(exc)[:300]
        await db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await db.commit()
    return {"id": str(store.id), "status": "Provisioning"}
