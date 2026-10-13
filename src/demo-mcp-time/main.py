"""HTTP entrypoint: FastMCP + Streamable HTTP plus K8s probes (demo Time server).

Mirrors the woo-mcp bootstrap: FastMCP with `json_response=True` (POST /mcp answers
JSON) and `stateless_http=True` (no `Mcp-Session-Id`, so replicas are interchangeable).
"""

from __future__ import annotations

import logging
import os

from config import get_settings
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from tools import register_tools

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("demo-time")

# The SDK logs an anyio ClosedResourceError per request when tearing down the
# stateless session; it is expected noise, so silence it.
for _noisy in ("mcp.server.streamable_http", "mcp.server.streamable_http_manager"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

mcp = FastMCP(
    settings.service_name,
    instructions=(
        "Time utilities: get the current UTC time (optionally in any IANA timezone) "
        "and convert a given time between two timezones."
    ),
    json_response=True,
    stateless_http=True,
)
mcp._mcp_server.version = settings.service_version

register_tools(mcp)

MCP_MOUNT = "/mcp"


async def healthz(request: Request) -> JSONResponse:
    """Liveness: no external dependencies, so a Woo/network outage never restarts us."""

    return JSONResponse(
        {
            "status": "ok",
            "service": settings.service_name,
            "version": settings.service_version,
            "transport": "streamable-http",
            "mcp_endpoint": MCP_MOUNT,
        }
    )


async def readyz(request: Request) -> JSONResponse:
    """Readiness: tools are registered and the timezone database is usable."""

    try:
        from zoneinfo import ZoneInfo

        ZoneInfo("UTC")
    except Exception:  # pragma: no cover - tzdata missing
        return JSONResponse({"status": "error", "reason": "zoneinfo unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})


async def root(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "service": settings.service_name,
            "version": settings.service_version,
            "mcp": {"endpoint": MCP_MOUNT, "transport": "streamable-http", "protocol": settings.mcp_protocol_version},
        }
    )


def create_app():
    """Reuse the SDK app (it already routes /mcp and owns the session-manager lifespan)
    and add the probe routes to the same router."""

    app = mcp.streamable_http_app()
    app.router.routes.extend(
        [
            Route("/", root, methods=["GET"]),
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
        ]
    )
    logger.info("demo-time ready (transport=%s)", MCP_MOUNT)
    return app


app = create_app()

if __name__ == "__main__":  # pragma: no cover - container entrypoint
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
