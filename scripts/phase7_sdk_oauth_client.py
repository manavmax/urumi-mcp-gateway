"""Phase 7b: drive the gateway with the MCP Python SDK's OWN OAuth client.

Uses mcp.client.auth.OAuthClientProvider (the SDK's RFC 9728/8414/7591 + PKCE
implementation) over streamablehttp_client: the SDK performs discovery,
registers itself, sends the browser to the authorize URL, and exchanges the
code. The "browser" part is automated: our BrowserRedirectProvider opens the
authorize URL with a logged-in dashboard session, approves the consent form,
and returns the redirect to the SDK.

Run from the HOST (the flow is entirely public-URL based):
  .venv/bin/python scripts/phase7_sdk_oauth_client.py
"""

from __future__ import annotations

import asyncio
import os
import re
from urllib.parse import parse_qs, urlparse

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientMetadata, OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamablehttp_client

BASE = "http://dashboard.127.0.0.1.nip.io"
ADMIN_EMAIL = "admin@urumi.local"
ADMIN_PASSWORD = os.environ.get("GATEWAY_ADMIN_PASSWORD", "")



class MemoryTokenStorage(TokenStorage):
    def __init__(self):
        self._tokens = None
        self._client_info = None

    async def get_tokens(self):
        return self._tokens

    async def set_tokens(self, tokens):
        self._tokens = tokens

    async def get_client_info(self):
        return self._client_info

    async def set_client_info(self, info):
        self._client_info = info


class DashboardBrowserProvider:
    """The 'browser': holds a dashboard session, follows the authorize URL,
    approves the consent form, and returns the final redirect URL to the SDK."""

    def __init__(self, base: str):
        self.base = base
        self.client = httpx.AsyncClient(base_url=base, timeout=30, follow_redirects=False)

    async def login(self, email: str, password: str):
        r = await self.client.post("/api/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        self.csrf = r.json()["csrf_token"]

    async def authorize(self, authorize_url: str) -> str:
        # the SDK gives us the AS's authorize URL (absolute): open it in-session
        url = authorize_url.replace(self.base, "") if authorize_url.startswith(self.base) else authorize_url
        if authorize_url.startswith("http"):
            path = urlparse(authorize_url).path + ("?" + urlparse(authorize_url).query if urlparse(authorize_url).query else "")
            url = path
        r = await self.client.get(url)
        r.raise_for_status()
        if r.status_code == 200 and "Authorize access" not in r.text:
            raise RuntimeError(f"unexpected authorize response: {r.status_code}")
        # approve: POST the same params the consent form echoed
        hidden = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', r.text))
        r = await self.client.post(
            "/oauth/authorize",
            data={**hidden, "decision": "approve"},
            headers={"X-CSRF-Token": self.csrf},
        )
        if r.status_code != 302:
            raise RuntimeError(f"consent approve failed: {r.status_code} {r.text[:200]}")
        # return the ABSOLUTE redirect URL to the SDK
        loc = r.headers["location"]
        if loc.startswith("/"):
            loc = self.base + loc
        return loc

    async def aclose(self):
        await self.client.aclose()


async def main() -> int:
    browser = DashboardBrowserProvider(BASE)
    await browser.login(ADMIN_EMAIL, ADMIN_PASSWORD)

    captured = {}

    async def _redirect(authorize_url: str) -> None:
        """The 'browser': open the authorize URL in the dashboard session,
        approve the consent form, and capture the code from the 302. The
        redirect_uri is the SDK's registered one (exact match) and the browser
        never needs to actually follow it."""
        import urllib.parse as up

        parts = up.urlparse(authorize_url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        path = parts.path + "?" + up.urlencode(q)
        r = await browser.client.get(path)
        r.raise_for_status()
        hidden = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', r.text))
        r = await browser.client.post(
            "/oauth/authorize", data={**hidden, "decision": "approve"},
            headers={"X-CSRF-Token": browser.csrf},
        )
        if r.status_code != 302:
            raise RuntimeError(f"consent failed: {r.status_code}")
        captured.update(parse_qs(urlparse(r.headers["location"]).query))

    async def _callback() -> tuple[str, str | None]:
        return captured.get("code", [""])[0], captured.get("state", [None])[0]

    client_metadata = OAuthClientMetadata(
        client_name="phase7-sdk-client",
        redirect_uris=["http://127.0.0.1:0/callback"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )

    provider = OAuthClientProvider(
        server_url=f"{BASE}/mcp",
        client_metadata=client_metadata,
        storage=MemoryTokenStorage(),
        redirect_handler=_redirect,
        callback_handler=_callback,
    )

    try:
        async with streamablehttp_client(f"{BASE}/mcp", auth=provider) as (read, write, _), ClientSession(read, write) as session:
            init = await asyncio.wait_for(session.initialize(), timeout=30)
            tools = await asyncio.wait_for(session.list_tools(), timeout=30)
            print("SDK initialize serverInfo:", init.serverInfo.name, init.serverInfo.version)
            print("SDK tools via OAuth:", len(tools.tools))
            result = await asyncio.wait_for(session.call_tool("time__get_current_time", {}), timeout=30)
            text = result.content[0].text if result.content else ""
            print("SDK tools/call:", str(text)[:100])
    finally:
        await browser.aclose()

    print("SDK-OAUTH-CLIENT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
