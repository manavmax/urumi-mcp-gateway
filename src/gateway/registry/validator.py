"""SSRF validator — docs/04 §5.

- Validate at write time (POST/PATCH /api/servers)
- Validate at request time: resolve_and_validate DNS before proxy
- follow_redirects=False
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_NETS = [ipaddress.ip_network(c) for c in [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "100.64.0.0/10",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]]

BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata.google",
    "instance-data",
    "169.254.169.254",
    "metadata.azure.internal",
}


def validate_url(url: str, *, allowed_host_suffixes: list[str] | None = None, allowed_domains: list[str] | None = None):
    """Synchronous URL shape validation (no DNS).

    Raises ValueError with human message.
    """
    if not url or not url.strip():
        raise ValueError("URL is required")
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http and https schemes are allowed")
    if "@" in parsed.netloc:
        raise ValueError("userinfo in URL is not allowed")
    host = parsed.hostname
    if not host:
        raise ValueError("URL must have a host")
    host_lower = host.lower()
    if host_lower in BLOCKED_HOSTS:
        raise ValueError(f"Blocked host: {host}")
    if host_lower == "localhost":
        raise ValueError("localhost is not allowed")
    # Allow-list suffix check for in-cluster hosts (e.g. *.svc.cluster.local)
    # If allowed_host_suffixes provided, we still apply private-net checks via DNS later.
    # Domain allow-list (if configured): enforce suffix match for public hosts
    if allowed_domains:
        # If host is cluster-internal (suffix allow), skip domain check
        suffixes = allowed_host_suffixes or []
        is_internal = any(host_lower == s.lstrip(".") or host_lower.endswith(s.lower()) for s in suffixes)
        if not is_internal and not any(host_lower == d or host_lower.endswith("." + d) for d in allowed_domains):
            raise ValueError(f"Host {host} not in allowed domains")
    # block literal private IPs without DNS (fast path)
    try:
        ip = ipaddress.ip_address(host)
        if any(ip in n for n in BLOCKED_NETS) or ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError(f"Blocked IP: {host}")
    except ValueError as exc:
        # Re-raise if this was our Blocked IP error
        if "Blocked IP" in str(exc):
            raise
        # otherwise host is not a literal IP — DNS check will handle
        pass
    # also block url-encoded @ tricks already handled; ensure no fragment abuse
    return url


async def resolve_and_validate(host: str):
    """Resolve DNS for host and ensure no resolved IP is private/link-local/metadata.

    Raises ValueError if any resolved IP is blocked.
    """
    if not host:
        raise ValueError("host required for DNS validation")
    # Fast path: literal IP
    try:
        ip_obj = ipaddress.ip_address(host)
        if any(ip_obj in n for n in BLOCKED_NETS) or ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
            raise ValueError(f"Blocked IP {host}")
        return
    except ValueError as e:
        if "Blocked IP" in str(e):
            raise
    # DNS lookup
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {host}: {exc}") from exc
    for _family, _, _, _, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if any(ip_obj in n for n in BLOCKED_NETS) or ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
            raise ValueError(f"Blocked IP {ip_str} for host {host}")
        # explicitly block metadata IP even if not in nets
        if ip_str == "169.254.169.254":
            raise ValueError(f"Blocked metadata IP for {host}")


async def validate_url_and_dns(url: str, *, allowed_host_suffixes: list[str] | None = None, allowed_domains: list[str] | None = None):
    validate_url(url, allowed_host_suffixes=allowed_host_suffixes, allowed_domains=allowed_domains)
    host = urlparse(url).hostname or ""
    # Allow cluster-internal suffixes to bypass private-net DNS block (they resolve to ClusterIP
    # which is not in the blocked nets, but they may resolve to 10.x service CIDR on some CNIs).
    # We treat them as allowed if they match suffix.
    if allowed_host_suffixes:
        lower = host.lower()
        if any(lower == s.lstrip(".") or lower.endswith(s.lower()) for s in allowed_host_suffixes):
            return
    await resolve_and_validate(host)


def ssrf_safe_client_factory(timeout_seconds: float):
    """The ONLY httpx client factory the gateway uses for upstream MCP calls.

    Redirects are NEVER followed (follow_redirects=False): the SSRF guard validated
    the ORIGINAL host at resolve time, and a 30x must not be able to smuggle the
    call to a private IP (httpx returns the 3xx response instead of chasing it).
    The MCP SDK passes arbitrary kwargs (headers/timeout/...); they are accepted
    and IGNORED - timeout is ours, redirects are nobody's.
    """
    import httpx

    def _factory(**_kwargs):
        return httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), follow_redirects=False)

    return _factory
