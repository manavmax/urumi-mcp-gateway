"""Gateway FastAPI app with lifespan (health + audit) + routes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from contextlib import asynccontextmanager

from config import get_settings
from db.session import get_session_factory
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

LOG_FORMAT = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'

# Hardening (ADR-046): security headers on every gateway response. The API serves
# JSON only, so the CSP is a defence-in-depth cap on what a response COULD render
# if a content-type ever went wrong: self-only scripts/styles/connects, no
# framing, no inline anything. The dashboard's nginx sets the same policy for the
# SPA (src/dashboard/nginx.conf).
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    # Deliberately empty value (the spec allows an empty policy = all features
    # denied by default on browsers that honour it).
    "Permissions-Policy": "",
}


def configure_logging():
    """(Re-)install the gateway's own logging config.

    Alembic's `Config(alembic.ini)` runs `logging.config.fileConfig()` on the ini's
    [loggers] section, with `disable_existing_loggers=True`: it replaces the root
    handler *and* sets `disabled=True` on the already-created "gateway" logger, so every
    line logged after the migration is dropped - which is how a failing startup step once
    went completely unnoticed. Re-applying after the upgrade keeps startup observable.
    """
    try:
        level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    except Exception:
        level = logging.INFO
    logging.basicConfig(level=level, format=LOG_FORMAT, force=True)
    logger.disabled = False


logger = logging.getLogger("gateway")

configure_logging()

# silence noisy mcp logs in gateway (we proxy, not serve FastMCP here)
for _n in ("mcp.server.streamable_http", "mcp.server.streamable_http_manager"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    logger.info("gateway starting version=%s", settings.service_version)

    # Auto-migrate + seed on startup (K8s: gateway starts after postgres is ready)
    try:
        from alembic import command
        from alembic.config import Config

        alembic_ini = os.path.join(os.path.dirname(__file__), "alembic.ini")
        if os.path.exists(alembic_ini):
            cfg = Config(alembic_ini)
            # override url from env
            db_url = settings.database_url
            cfg.set_main_option("sqlalchemy.url", db_url)
            # run in thread to avoid blocking event loop
            import asyncio as _asyncio

            await _asyncio.to_thread(command.upgrade, cfg, "head")
            # alembic's fileConfig reconfigures logging: restore ours, or nothing logged
            # from here on (seed errors included) is ever seen
            configure_logging()
            logger.info("alembic upgrade head done")
    except Exception as exc:
        logger.warning("alembic upgrade failed (will retry on next start): %s", exc)

    # seed default servers + the administrator account
    try:
        factory = get_session_factory()
        async with factory() as db:
            # seed servers
            from registry.crud import resync_internal_credentials, seed_default_servers

            await seed_default_servers(db)
            # Seeded internal upstreams are authoritative: their credential comes from
            # the environment/Secret, re-encrypted with the CURRENT Fernet key, so a
            # rotated Secret or key self-heals on this start instead of failing every
            # tool call with a key mismatch (docs/DECISIONS.md ADR-026). Admin-added
            # servers are never touched; only the slug is logged, never the value.
            for slug in await resync_internal_credentials(db):
                logger.info("re-synced credential for %s", slug)
            # seed / rotate the administrator. The password comes from the
            # `gateway-admin` Secret (env GATEWAY_ADMIN_PASSWORD) which the chart generates
            # at install (docs/DECISIONS.md ADR-019/021). There is deliberately no default
            # in this file: an empty value skips the bootstrap instead of inventing a
            # credential.
            from auth.rbac import hash_password, verify_password
            from db.models import User

            res = await db.execute(select(User).where(User.email == settings.admin_email))
            user = res.scalars().first()
            if not settings.admin_password:
                logger.warning(
                    "GATEWAY_ADMIN_PASSWORD is not set: skipping admin bootstrap for %s "
                    "(the chart always renders the gateway-admin Secret; read the value with "
                    "'make gateway-admin-password')",
                    settings.admin_email,
                )
            elif user is None:
                pw = await hash_password(settings.admin_password)
                db.add(User(email=settings.admin_email, password_hash=pw, role="admin"))
                logger.info(
                    "seeded administrator %s (password taken from the gateway-admin Secret)",
                    settings.admin_email,
                )
            elif not await verify_password(user.password_hash, settings.admin_password):
                # A database carried over from an earlier build can still hold a hash of
                # the default that used to be committed in this file. The Secret is the
                # source of truth, so rotate on start rather than leave a known credential
                # on a dashboard that is reachable through the Ingress.
                user.password_hash = await hash_password(settings.admin_password)
                logger.info(
                    "rotated the password for %s to the gateway-admin Secret value",
                    settings.admin_email,
                )
            await db.commit()
    except Exception as exc:
        logger.warning("seeding failed: %s", exc)

    # background tasks
    audit_task = None
    health_task = None
    upload_purge_task = None
    try:
        from audit.queue import audit_worker
        from gw_mcp.health import health_loop

        audit_task = asyncio.create_task(audit_worker())
        health_task = asyncio.create_task(health_loop())
        app.state.audit_task = audit_task
        app.state.health_task = health_task
        # Phase 5 (ADR-060): store status sync (no-op unless stores_enabled)
        from stores.sync import sync_loop

        store_sync_task = asyncio.create_task(sync_loop())
        app.state.store_sync_task = store_sync_task
        # F3: chat uploads live 15 minutes — sweep expired rows every minute.
        from datetime import UTC, datetime

        async def upload_purge_loop():
            from db.models import ChatUpload
            from db.session import get_session_factory
            from sqlalchemy import delete

            while True:
                await asyncio.sleep(60)
                try:
                    factory = get_session_factory()
                    async with factory() as db:
                        await db.execute(delete(ChatUpload).where(ChatUpload.expires_at <= datetime.now(UTC)))
                        await db.commit()
                except Exception as exc:
                    logger.warning("chat upload purge failed: %s", exc)
                # ADR-057: sweep expired rate-limit minute windows (5-minute keep)
                try:
                    from auth.rate_limit import purge_old_counters

                    await purge_old_counters()
                except Exception as exc:
                    logger.warning("rate limit purge failed: %s", exc)
                # ADR-059: sweep expired login-lockout failure rows (window x2 keep)
                try:
                    from auth.login_throttle import purge_old_failures

                    await purge_old_failures()
                except Exception as exc:
                    logger.warning("login failure purge failed: %s", exc)

        upload_purge_task = asyncio.create_task(upload_purge_loop())
        app.state.upload_purge_task = upload_purge_task
    except Exception as exc:
        logger.warning("failed to start background tasks: %s", exc)

    yield

    # shutdown
    for t in [audit_task, health_task, upload_purge_task, store_sync_task]:
        if t:
            t.cancel()
            # awaiting a cancelled task re-raises CancelledError, which is expected
            with contextlib.suppress(asyncio.CancelledError):
                await t
    try:
        from db.session import dispose_engine

        await dispose_engine()
    except Exception:
        pass
    logger.info("gateway shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title="Urumi Gateway", version=get_settings().service_version, lifespan=lifespan)

    # request-id middleware
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    # security headers middleware (ADR-046)
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    # CORS for dashboard dev (when dashboard is separate origin)
    cors_origins = [o.strip() for o in get_settings().cors_allow_origins.split(",") if o.strip()]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # routes
    from routes.admin_events import router as admin_events_router
    from routes.alerts import router as alerts_router
    from routes.audit import router as audit_router
    from routes.chat import router as chat_router
    from routes.chat_uploads import router as chat_uploads_router
    from routes.health import router as health_router
    from routes.mcp import router as mcp_router
    from routes.metrics import router as metrics_router
    from routes.notifications import router as notifications_router
    from routes.permissions import router as permissions_router
    from routes.servers import router as servers_router
    from routes.stats import router as stats_router
    from routes.tools import router as tools_router
    from routes.users import router as users_router

    app.include_router(health_router)
    app.include_router(mcp_router)
    app.include_router(metrics_router)
    app.include_router(alerts_router)
    app.include_router(notifications_router)
    app.include_router(permissions_router)
    app.include_router(servers_router)
    app.include_router(users_router)
    app.include_router(audit_router)
    app.include_router(admin_events_router)
    app.include_router(tools_router)
    app.include_router(stats_router)
    app.include_router(chat_router)
    app.include_router(chat_uploads_router)

    # Phase 5 (ADR-060): per-user storefronts (403 everywhere when the flag is off)
    from stores.routes import router as stores_router

    app.include_router(stores_router)

    # Phase 6 (ADR-062): hosted MCP servers (admin-only, 403 when the flag is off)
    from hosted.routes import router as hosted_router

    app.include_router(hosted_router)

    @app.get("/")
    async def root():
        s = get_settings()
        return {"service": s.service_name, "version": s.service_version, "mcp": "/mcp", "api": "/api"}

    return app


app = create_app()

if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
