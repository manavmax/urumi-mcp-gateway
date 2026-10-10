"""HTTP entrypoint: FastMCP + Streamable HTTP transport plus K8s probes.

Per docs/03 §5 the server is ClusterIP-only (no Ingress) and exposes:
  POST /mcp     - JSON-RPC (initialize / tools/list / tools/call)
  GET  /mcp     - SSE stream (kept for spec completeness; we answer POST with JSON)
  GET  /healthz - liveness (no external deps)
  GET  /readyz  - readiness: actually reaches WooCommerce wc/v3
"""

from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from config import get_settings
from tools import register_tools
from woo_client import WooRestClient

logging.basicConfig(
    level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("woo-mcp")

# In stateless mode the SDK tears the per-request session down immediately and logs an
# anyio ClosedResourceError at ERROR level for every request. It is expected (no
# Mcp-Session-Id is kept), so silence it to keep pod logs demo-quality.
for _noisy_logger in ("mcp.server.streamable_http", "mcp.server.streamable_http_manager"):
    logging.getLogger(_noisy_logger).setLevel(logging.CRITICAL)

settings = get_settings()

# --- MCP server ---------------------------------------------------------------
# json_response=True  -> POST /mcp answers application/json (no SSE stream needed)
# stateless_http=True -> no Mcp-Session-Id, so any number of replicas/redeploys
#                        keep working (matches the stateless gateway design)
mcp = FastMCP(
    settings.service_name,
    instructions=(
        "WooCommerce products and orders. Use woo tools to list/get/create "
        "products, list/get orders and update an order's status."
    ),
    json_response=True,
    stateless_http=True,
)
# FastMCP defaults serverInfo.version to the SDK's own version; advertise ours.
mcp._mcp_server.version = settings.service_version

# --- Woo REST client (single instance, reused connection pool) ----------------
woo_client = WooRestClient(
    settings.woo_url,
    settings.woo_consumer_key,
    settings.woo_consumer_secret,
    timeout_seconds=settings.woo_timeout_seconds,
)

register_tools(mcp, woo_client)

MCP_MOUNT = "/mcp"

# --- probes --------------------------------------------------------------------
async def healthz(request: Request) -> Response:
    """Liveness: the process is up. Never touches Woo (a Woo outage must not
    trigger a restart loop)."""

    return JSONResponse(
        {
            "status": "ok",
            "service": settings.service_name,
            "version": settings.service_version,
            "transport": "streamable-http",
            "mcp_endpoint": MCP_MOUNT,
        }
    )


async def readyz(request: Request) -> Response:
    """Readiness: WooCommerce wc/v3 is reachable with the configured credentials."""

    try:
        reachable = await woo_client.ping()
    except Exception:  # pragma: no cover - defensive
        reachable = False
    if reachable:
        return JSONResponse({"status": "ready", "woo": settings.woo_url})
    return JSONResponse(
        {"status": "unready", "woo": settings.woo_url, "reason": "wc/v3 unreachable"},
        status_code=503,
    )


async def root(request: Request) -> Response:
    return JSONResponse(
        {
            "service": settings.service_name,
            "version": settings.service_version,
            "mcp": {"endpoint": MCP_MOUNT, "transport": "streamable-http", "protocol": settings.mcp_protocol_version},
        }
    )


def create_app() -> Starlette:
    """Build the ASGI app: the SDK app already serves `<mount>/mcp`, so we reuse it
    (keeping its lifespan, which starts the StreamableHTTPSessionManager) and add
    the probe routes to the same router."""

    mcp_app = mcp.streamable_http_app()  # includes the /mcp route + session-manager lifespan
    mcp_app.router.routes.extend(
        [
            Route("/", root, methods=["GET"]),
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
        ]
    )
    logger.info(
        "woo-mcp ready (url=%s, transport=%s)", settings.woo_url, MCP_MOUNT
    )
    return mcp_app


app = create_app()


if __name__ == "__main__":  # pragma: no cover - container entrypoint
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
