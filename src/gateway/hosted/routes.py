"""Hosted MCP server routes (Phase 6, ADR-062).

Admin-only. POST /api/hosted {name, image, port, env:{k:v}} -> the provisioner
deploys hosted-<name>; GET /api/hosted lists rows (env NAMES only, never
values); DELETE /api/hosted/{id} tears the namespace down. On Ready the sync
loop registers an internal upstream Server row (slug = name) so the tools show
up as <name>__*.

Image rules: a tag or digest is REQUIRED, :latest refused, and an optional
registry allowlist (hostedServers.allowedRegistries) is enforced. Env VALUES
are sent to the provisioner once (which stores them in a K8s Secret) and are
never persisted gateway-side nor echoed back.
"""

from __future__ import annotations

import uuid

from audit.admin_events import record_admin_event
from auth.rbac import get_current_user_via_session, verify_csrf
from db.models import HostedServer, Server, Store
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

RESERVED_NAMES = {
    "hosted", "hosteds", "provisioner", "internal", "gateway", "gateway-admin",
    "store", "stores", "time", "notes", "woo", "admin", "api", "auth",
}


def _validate_name(name: str) -> str:
    import re

    name = (name or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9]{0,28}[a-z0-9])?", name or ""):
        raise HTTPException(status_code=400, detail="name must be 1-30 chars: lowercase letters, digits, dashes")
    if name in RESERVED_NAMES:
        raise HTTPException(status_code=400, detail="that name is reserved")
    return name


def _validate_image(image: str) -> str:
    from config import get_settings

    image = (image or "").strip()
    if "/" not in image:
        raise HTTPException(status_code=400, detail="image must include a registry (e.g. ghcr.io/urumi/demo-mcp-time:0.1.0)")
    last = image.split("/")[-1]
    if ":" not in last and "@" not in image:
        raise HTTPException(status_code=400, detail="image needs a tag or digest (e.g. ...:0.1.0)")
    if image.endswith(":latest"):
        raise HTTPException(status_code=400, detail=":latest is not allowed; pin a version tag or digest")
    # Normalise each entry (ADR-090): strip whitespace AND a trailing slash, so
    # "ghcr.io/manavmax/" and "ghcr.io/manavmax" behave identically; empty
    # entries are ignored. The "/" boundary below is kept, so ghcr.io/manavmax
    # never matches ghcr.io/manavmax-evil/....
    allow = [a.strip().rstrip("/") for a in (get_settings().hosted_registry_allowlist or "").split(",")]
    allow = [a for a in allow if a]
    if allow and not any(image == a or image.startswith(a + "/") for a in allow):
        raise HTTPException(status_code=400, detail="image registry is not on the allowlist")
    return image


def _validate_env(env: dict) -> dict[str, str]:
    if env is None:
        return {}
    if not isinstance(env, dict):
        raise HTTPException(status_code=400, detail="env must be an object of name -> value")
    out: dict[str, str] = {}
    for k, v in env.items():
        k = str(k)
        if not k or not (k[0].isalpha() or k[0] == "_") or not all(c.isalnum() or c == "_" for c in k):
            raise HTTPException(status_code=400, detail=f"env name {k!r} must be a simple identifier")
        if not isinstance(v, str) or len(v) > 4096:
            raise HTTPException(status_code=400, detail=f"env value for {k!r} must be a string (<= 4096 chars)")
        out[k] = v
    if len(out) > 32:
        raise HTTPException(status_code=400, detail="at most 32 env vars")
    return out


def _hosted_out(h: HostedServer, is_admin: bool) -> dict:
    return {
        "id": str(h.id),
        "name": h.name,
        "image": h.image,
        "port": h.port,
        "env_names": sorted(h.env_names or []),
        "status": h.status,
        "failure_reason": h.failure_reason,
        # the in-cluster URL the gateway's upstream will use once Ready
        # (hosted-<name> namespace, service name == name)
        "url": f"http://{h.name}.hosted-{h.name}.svc:{h.port}/mcp",
        "created_at": h.created_at.isoformat() if h.created_at else None,
        "updated_at": h.updated_at.isoformat() if h.updated_at else None,
    }


def _require_hosted_enabled() -> None:
    from config import get_settings

    if not get_settings().hosted_enabled:
        raise HTTPException(status_code=403, detail="hosted servers are disabled on this deployment")


@router.get("/api/hosted")
async def list_hosted(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    _require_hosted_enabled()
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    rows = (
        await db.execute(select(HostedServer).order_by(HostedServer.created_at.desc()))
    ).scalars().all()
    return {"hosted": [_hosted_out(h, is_admin=True) for h in rows]}


@router.post("/api/hosted", status_code=201)
async def create_hosted(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    _require_hosted_enabled()
    verify_csrf(request)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    body = await request.json()
    name = _validate_name(str(body.get("name") or ""))
    image = _validate_image(str(body.get("image") or ""))
    port = body.get("port")
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="port must be an integer") from None
    if not (1 <= port <= 65535):
        raise HTTPException(status_code=400, detail="port must be 1-65535")
    env = _validate_env(body.get("env") or {})

    from config import get_settings

    settings = get_settings()
    total = (await db.execute(select(func.count()).select_from(HostedServer))).scalar() or 0
    if total >= settings.hosted_global_max:
        raise HTTPException(status_code=400, detail=f"the hosted server limit is reached ({settings.hosted_global_max})")
    clash = (await db.execute(select(HostedServer).where(HostedServer.name == name))).scalars().first()
    if clash:
        raise HTTPException(status_code=400, detail="a hosted server with that name already exists")
    srv_clash = (await db.execute(select(Server).where(Server.slug == name))).scalars().first()
    if srv_clash:
        raise HTTPException(status_code=400, detail="that name collides with a registered server slug")
    store_clash = (await db.execute(select(HostedServer))).scalars().all()
    if any(name == h.name for h in store_clash):
        raise HTTPException(status_code=400, detail="a hosted server with that name already exists")


    st = (await db.execute(select(Store).where(Store.slug == name))).scalars().first()
    if st:
        raise HTTPException(status_code=400, detail="that name collides with a store slug")

    hosted = HostedServer(
        name=name,
        image=image,
        port=port,
        env_names=sorted(env.keys()),
        status="Provisioning",
        created_by=user.id,
    )
    db.add(hosted)
    await db.flush()

    from stores.client import host_server

    try:
        await host_server(name, image, port, env)
    except Exception as exc:
        hosted.status = "Failed"
        hosted.failure_reason = str(exc)[:300]
        await db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    record_admin_event(
        db,
        actor_user_id=user.id,
        action="hosted.create",
        target_type="hosted",
        target_ref=name,
        details={"hosted_id": str(hosted.id), "image": image, "port": port, "env_names": sorted(env.keys())},
    )
    await db.commit()
    return _hosted_out(hosted, is_admin=True)


@router.delete("/api/hosted/{hosted_id}", status_code=200)
async def delete_hosted(
    hosted_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    _require_hosted_enabled()
    verify_csrf(request)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    hosted = (await db.execute(select(HostedServer).where(HostedServer.id == hosted_id))).scalars().first()
    if hosted is None:
        raise HTTPException(status_code=404, detail="hosted server not found")
    if hosted.status == "Deleting":
        return _hosted_out(hosted, is_admin=True)
    hosted.status = "Deleting"
    await db.flush()

    from stores.client import unhost_server

    try:
        await unhost_server(hosted.name)
    except Exception as exc:
        hosted.status = "Failed"
        hosted.failure_reason = str(exc)[:300]
        await db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    record_admin_event(
        db,
        actor_user_id=user.id,
        action="hosted.delete",
        target_type="hosted",
        target_ref=hosted.name,
        details={"hosted_id": str(hosted.id)},
    )
    await db.commit()
    return _hosted_out(hosted, is_admin=True)
