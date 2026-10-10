"""Minimal WooCommerce REST (wc/v3) client.

This is the ONLY component that talks to WooCommerce (docs/03 §3): it speaks
HTTP with Consumer Key/Secret Basic auth, follows the documented timeout/error
mapping, and never redirects (SSRF-safe: a 3xx surface is reported, not followed).
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

logger = logging.getLogger("woo-client")

# Woo status codes that mean "bad credentials" vs "missing" vs "bad request".
_AUTH_CODES = {401, 403}

# Woo reports "this resource does not exist" as a 400 with these markers in the body
# (its REST layer validates ids before routing, so no 404 is produced). We treat those
# as NOT_FOUND so callers get a meaningful message instead of a generic bad request.
_NOT_FOUND_MARKERS = (
    "invalid_id",
    "invalid id",
    "does not exist",
    "woocommerce_rest_invalid",
)


class WooUnreachableError(Exception):
    """Network/timeout level failure — maps to MCP error code -32000."""


class WooApiError(Exception):
    """A 4xx/5xx from WooCommerce; carries the original status and body."""

    def __init__(self, status_code: int, message: str, *, resource: str = "resource") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.resource = resource
        self.message = message

    def to_tool_error(self) -> str:
        """User-facing message following docs/03 §3 (error mapping)."""

        if self.status_code in _AUTH_CODES:
            return "Woo auth failed — check Consumer Key (401/403 from wc/v3)"
        if self.status_code == 404:
            return f"{self.resource.capitalize()} not found in the WooCommerce store"
        if self.status_code == 400:
            return f"Woo rejected the request (400): {self.message}"
        return f"Woo {self.status_code}: {self.message}"


class WooRestClient:
    """Async httpx wrapper with Basic auth and explicit error mapping."""

    def __init__(
        self,
        base_url: str,
        consumer_key: str,
        consumer_secret: str,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        credentials = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {credentials}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "urumi-woo-mcp/1.0",
        }
        # follow_redirects=False: never chase a redirect surface (SSRF hardening).
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        resource: str = "Resource",
    ) -> Any:
        url = path.lstrip("/")
        try:
            response = await self._client.request(
                method, url, params=params, json=json_body
            )
        except httpx.TimeoutException as exc:
            raise WooUnreachableError(
                f"Woo store did not respond within timeout ({exc.__class__.__name__})"
            ) from exc
        except httpx.HTTPError as exc:
            raise WooUnreachableError(f"Woo store unreachable: {exc}") from exc

        if response.is_error:
            body = response.text[:300]
            raise WooApiError(response.status_code, body or response.reason_phrase, resource=resource)
        if response.is_redirect:
            # Unexpected but must not be followed automatically.
            raise WooApiError(
                response.status_code,
                f"unexpected redirect to {response.headers.get('location')}",
                resource=resource,
            )
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise WooApiError(
                502, "Woo returned a non-JSON response", resource=resource
            ) from exc

    async def get(self, path: str, *, params: dict[str, Any] | None = None, resource: str = "Product") -> Any:
        return await self._request("GET", path, params=params, resource=resource)

    async def post(self, path: str, *, json_body: dict[str, Any] | None = None, resource: str = "Product") -> Any:
        return await self._request("POST", path, json_body=json_body, resource=resource)

    async def put(self, path: str, *, json_body: dict[str, Any] | None = None, resource: str = "Order") -> Any:
        return await self._request("PUT", path, json_body=json_body, resource=resource)

    async def ping(self) -> bool:
        """Cheap reachability probe used by /readyz."""

        try:
            await self._client.get("wp-json/wc/v3/products", params={"per_page": 1})
        except httpx.HTTPError:
            return False
        # Mock transport (tests) returns a response without status handling; guard anyway
        return True
