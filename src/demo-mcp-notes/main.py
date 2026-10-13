"""HTTP entrypoint for the demo Notes MCP server (token-protected Streamable HTTP)."""

from __future__ import annotations

import logging
import os

from auth import BearerTokenMiddleware
from config import get_settings
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from tools import NoteStore, register_tools

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("demo-notes")

for _noisy in ("mcp.server.streamable_http", "mcp.server.streamable_http_manager"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

mcp = FastMCP(
    settings.service_name,
    instructions=(
        "Simple notes: create a note, list all notes, or search notes by title or "
        "body. A bearer token is required for every request."
    ),
    json_response=True,
    stateless_http=True,
)
mcp._mcp_server.version = settings.service_version

register_tools(mcp, NoteStore())

MCP_MOUNT = "/mcp"


async def healthz(request: Request) -> JSONResponse:
    """Open to probes; a missing token is a deploy failure, not a health failure."""

    return JSONResponse(
        {
            "status": "ok",
            "service": settings.service_name,
            "version": settings.service_version,
            "transport": "streamable-http",
            "requires_token": True,
            "mcp_endpoint": MCP_MOUNT,
        }
    )


async def readyz(request: Request) -> JSONResponse:
    """Ready only when the token is actually configured (probes + ops sanity)."""

    if not settings.notes_api_token.strip():
        return JSONResponse(
            {"status": "error", "reason": "NOTES_API_TOKEN not set"}, status_code=503
        )
    return JSONResponse({"status": "ready", "authenticated": True})


async def root(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "service": settings.service_name,
            "version": settings.service_version,
            "auth": "bearer (all /mcp requests)",
            "mcp": {"endpoint": MCP_MOUNT, "transport": "streamable-http", "protocol": settings.mcp_protocol_version},
        }
    )


def create_app():
    """Same bootstrap as woo-mcp: reuse the SDK app for /mcp + its lifespan, then add
    probe routes and wrap the whole thing in the bearer-token middleware."""

    app = mcp.streamable_http_app()
    app.router.routes.extend(
        [
            Route("/", root, methods=["GET"]),
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
        ]
    )

    token = settings.notes_api_token.strip()
    if not token:
        # Fail fast at import: this server must never serve without its Secret.
        settings.require_token()

    app.add_middleware(BearerTokenMiddleware, token=token)
    logger.info("demo-notes ready (transport=%s, bearer token required)", MCP_MOUNT)
    return app


app = create_app()

if __name__ == "__main__":  # pragma: no cover - container entrypoint
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
