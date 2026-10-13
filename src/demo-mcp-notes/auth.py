"""Bearer-token middleware for the demo Notes MCP.

The task requires a hard 401 without the token so the gateway can demonstrate
credential injection. This is enforced by a dedicated ASGI middleware (before any
MCP routing) so even a malformed MCP request is rejected unauthenticated.

Rules:
  - `/healthz`, `/readyz` and `/` stay open (Kubernetes probes must work unauthenticated)
  - every other path requires `Authorization: Bearer <NOTES_API_TOKEN>`
  - constant-time comparison; the token value is never logged
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

logger = logging.getLogger("demo-notes.auth")

OPEN_PATHS = frozenset({"/healthz", "/readyz", "/"})


class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, token: str, open_paths: Iterable[str] = OPEN_PATHS) -> None:
        super().__init__(app)
        self._token = token.strip()
        self._open = set(open_paths)

    def _authorized(self, header: str | None) -> bool:
        if not header:
            return False
        parts = header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False
        return hmac.compare_digest(parts[1].strip(), self._token)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._open:
            return await call_next(request)

        if not self._authorized(request.headers.get("authorization")):
            return JSONResponse(
                {
                    "error": "unauthorized",
                    "message": "Missing or invalid bearer token",
                    "hint": "Send: Authorization: Bearer <token>",
                },
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="demo-notes-mcp"'},
            )
        return await call_next(request)
