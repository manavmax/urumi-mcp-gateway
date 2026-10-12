"""Gateway FastAPI app with lifespan (health + audit) + routes."""

from __future__ import annotations

import asyncio
import logging
import uuid

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from db.session import get_session_factory
from sqlalchemy import select, text

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("gateway")

# silence noisy mcp logs in gateway (we proxy, not serve FastMCP here)
for _n in ("mcp.server.streamable_http", "mcp.server.streamable_http_manager"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.getLogger().setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.info("gateway starting version=%s", settings.service_version)

    # Auto-migrate + seed on startup (K8s: gateway starts after postgres is ready)
    try:
        from alembic.config import Config
        from alembic import command
        import os

        alembic_ini = os.path.join(os.path.dirname(__file__), "alembic.ini")
        if os.path.exists(alembic_ini):
            cfg = Config(alembic_ini)
            # override url from env
            db_url = settings.database_url
            cfg.set_main_option("sqlalchemy.url", db_url)
            # run in thread to avoid blocking event loop
            import asyncio as _asyncio

            await _asyncio.to_thread(command.upgrade, cfg, "head")
            logger.info("alembic upgrade head done")
    except Exception as exc:
        logger.warning("alembic upgrade failed (will retry on next start): %s", exc)

    # seed default servers + admin user
    try:
        factory = get_session_factory()
        async with factory() as db:
            # seed servers
            from registry.crud import seed_default_servers

            await seed_default_servers(db)
            # seed admin user if none exists
            from db.models import User
            from auth.rbac import hash_password

            res = await db.execute(select(User).where(User.email == "admin@urumi.local"))
            if not res.scalars().first():
                # create default admin: admin@urumi.local / admin123
                # Password is for local dev; prod should create via API with proper password
                pw = await hash_password("admin123")
                u = User(email="admin@urumi.local", password_hash=pw, role="admin")
                db.add(u)
                logger.info("seeded default admin admin@urumi.local")
            # also show count
            await db.commit()
    except Exception as exc:
        logger.warning("seeding failed: %s", exc)

    # Notes token injection: if NOTES_API_TOKEN env present and notes server has no cred, set it
    try:
        import os

        token = os.environ.get("NOTES_API_TOKEN") or os.environ.get("notes_api_token") or ""
        if token:
            from sqlalchemy import select

            factory = get_session_factory()
            async with factory() as db:
                from db.models import Server
                from registry.crypto import encrypt

                res = await db.execute(select(Server).where(Server.slug == "notes"))
                srv = res.scalars().first()
                if srv and not srv.credential_encrypted:
                    srv.credential_encrypted = encrypt(token)
                    srv.auth_type = "bearer"
                    await db.commit()
                    logger.info("injected NOTES_API_TOKEN into notes server")
    except Exception as exc:
        logger.warning("notes token injection failed: %s", exc)

    # background tasks
    audit_task = None
    health_task = None
    try:
        from audit.queue import audit_worker
        from gw_mcp.health import health_loop

        audit_task = asyncio.create_task(audit_worker())
        health_task = asyncio.create_task(health_loop())
        app.state.audit_task = audit_task
        app.state.health_task = health_task
    except Exception as exc:
        logger.warning("failed to start background tasks: %s", exc)

    yield

    # shutdown
    for t in [audit_task, health_task]:
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
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
    from routes.health import router as health_router
    from routes.mcp import router as mcp_router
    from routes.servers import router as servers_router
    from routes.users import router as users_router
    from routes.audit import router as audit_router
    from routes.tools import router as tools_router
    from routes.chat import router as chat_router

    app.include_router(health_router)
    app.include_router(mcp_router)
    app.include_router(servers_router)
    app.include_router(users_router)
    app.include_router(audit_router)
    app.include_router(tools_router)
    app.include_router(chat_router)

    @app.get("/")
    async def root():
        s = get_settings()
        return {"service": s.service_name, "version": s.service_version, "mcp": "/mcp", "api": "/api"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    import os

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
