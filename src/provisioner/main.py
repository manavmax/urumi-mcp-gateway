"""Provisioner HTTP service (Phase 5, ADR-060).

A tiny internal-only API the GATEWAY calls to create and tear down per-store
namespaces + helm releases. Not the Ingress, no dashboard: reachable only
from gateway pods (NetworkPolicy) and additionally guarded by the shared
X-Provisioner-Token (constant-time compare; the token lives in the
provisioner-token Secret).

  POST   /v1/stores          {slug}          -> 202 {phase}
  GET    /v1/stores/{slug}                   -> {phase, reason}
  DELETE /v1/stores/{slug}                   -> 202 {phase}
  GET    /healthz | /readyz                  -> liveness/readiness

All state derives from the cluster (labeled namespaces + helm releases), so a
provisioner restart resumes cleanly (reconcile loop).
"""

from __future__ import annotations

import hmac
import logging

from config import get_settings
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from slugs import StoreError, validate_slug
from starlette.responses import JSONResponse
from tasks import HelmRunner, TaskManager

logger = logging.getLogger("provisioner")

app = FastAPI(title="urumi-provisioner", docs_url=None, redoc_url=None, openapi_url=None)


class StoreRequest(BaseModel):
    slug: str


def make_app() -> FastAPI:
    return app


@app.on_event("startup")
async def _startup() -> None:
    import k8s
    from config import get_settings

    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    app.state.k8s = k8s.K8sClient()
    app.state.helm = HelmRunner()
    app.state.manager = TaskManager(app.state.k8s, app.state.helm)
    app.state.reconcile = None
    if settings.shared_token:
        logger.info("provisioner starting (token guard ACTIVE)")
    else:
        logger.warning("provisioner starting WITHOUT a shared token (dev mode)")
    import asyncio

    app.state.reconcile = asyncio.create_task(app.state.manager.reconcile_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    if getattr(app.state, "reconcile", None):
        app.state.reconcile.cancel()
    if getattr(app.state, "k8s", None):
        await app.state.k8s.aclose()


@app.middleware("http")
async def token_guard(request: Request, call_next):
    """Shared-secret guard on every /v1 route. Constant-time compare; the token
    is never logged. Health endpoints stay open for kubelet probes."""
    expected = get_settings().shared_token
    if expected and request.url.path.startswith("/v1/"):
        supplied = request.headers.get("x-provisioner-token", "")
        if not hmac.compare_digest(expected, supplied):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/readyz")
async def readyz():
    ok = hasattr(app.state, "manager")
    return JSONResponse({"ok": bool(ok)}, status_code=200 if ok else 503)


@app.post("/v1/stores", status_code=202)
async def create_store(body: StoreRequest, request: Request):
    try:
        slug = validate_slug(body.slug)
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # reset_clock=True: a POST is a NEW attempt (create or retry) - the
    # provisioning budget restarts. Reconcile resumes pass reset_clock=False
    # (they continue an existing attempt under its original budget).
    app.state.manager.start_provision(slug, reset_clock=True)
    logger.info("provisioning accepted for %s", slug)
    return {"phase": "provisioning", "slug": slug}


@app.get("/v1/stores/{slug}")
async def store_status(slug: str):
    try:
        validate_slug(slug)
        state = await app.state.manager.store_state(slug)
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return state


@app.delete("/v1/stores/{slug}", status_code=202)
async def delete_store(slug: str):
    try:
        validate_slug(slug)
        # refuse early when the namespace exists but is not managed
        from slugs import store_namespace

        obj = await app.state.k8s.get_namespace(store_namespace(slug))
        if obj is not None:
            await app.state.k8s.require_managed(store_namespace(slug))
        app.state.manager.start_deprovision(slug)
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("deprovisioning accepted for %s", slug)
    return {"phase": "deleting", "slug": slug}
