"""SSRF guard re-verification (hardening pass, item 5).

The validator (registry/validator.py) is the ONE gate for admin-added upstream
URLs. Pinned here, each row maps to a hardening-checklist item:

  save-time shape rejection (validate_url):
    127.0.0.1 / localhost / 169.254.169.254 / 10.x / 172.16.x / 192.168.x /
    IPv6 loopback / metadata hostnames
  connect-time resolution (resolve_and_validate - runs on EVERY proxy call,
    gw_mcp/router.py + gw_mcp/aggregator.py, not only at save time):
    literal private IPs, a hostname that RESOLVES to a private IP (mocked
    resolver), decimal/hex inet_aton forms (mocked resolver emulating glibc's
    acceptance of "2130706433" / "0x7f000001")
  redirects: the shared client factory used by both proxy call sites returns
    httpx clients with follow_redirects=False, so a 30x to a private IP is
    returned to the caller, never chased.

No live network: DNS is a monkeypatched getaddrinfo; the redirect behaviour is
asserted on the REAL factory's client attribute (httpx semantics: with
follow_redirects=False a 3xx response is returned unfollowed).
"""

from __future__ import annotations

import socket

import pytest
from registry import validator
from registry.validator import resolve_and_validate, ssrf_safe_client_factory, validate_url

# ---- save-time: validate_url shape rejection --------------------------------

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/mcp",
    "http://localhost:8000/mcp",
    "http://LOCALHOST:8000/mcp",  # case-insensitive
    "http://169.254.169.254/latest/meta-data/",
    "http://10.1.2.3:8000/mcp",
    "http://172.16.0.5:8000/mcp",
    "http://192.168.1.10:8000/mcp",
    "http://[::1]:8000/mcp",
    "http://[fe80::1]:8000/mcp",
    "http://metadata.google.internal/computeMetadata/v1/",
    "https://user:pass@example.com/mcp",  # userinfo smuggle
    "ftp://example.com",  # scheme allow-list
])
def test_validate_url_rejects_private_and_tricks(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize("url", [
    "http://urumi-demo-time:8000/mcp",   # in-cluster service (DNS-checked at call time)
    "https://api.example.com/v1",        # ordinary public host
])
def test_validate_url_accepts_legitimate(url):
    assert validate_url(url) == url


# ---- connect-time: resolve_and_validate --------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("host", [
    "127.0.0.1", "::1", "169.254.169.254", "10.0.0.1", "172.16.0.1", "192.168.0.1",
])
async def test_resolve_blocks_literal_private_ips(host):
    with pytest.raises(ValueError):
        await resolve_and_validate(host)


@pytest.mark.asyncio
async def test_resolve_blocks_hostname_resolving_to_private_ip(monkeypatch):
    """The core TOCTOU defence: the name is resolved and EVERY address is checked
    at request time - a hostname that only resolves private must be blocked even
    though its shape passed at save time."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port or 0))]

    monkeypatch.setattr(validator.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="Blocked IP"):
        await resolve_and_validate("attacker.example.com")


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["2130706433", "0x7f000001", "127.1"])
async def test_resolve_blocks_decimal_hex_ip_forms(monkeypatch, host):
    """glibc's resolver accepts inet_aton forms (decimal/hex/fewer-than-4-octet),
    so these MUST be caught by the resolved-address check, not trusted as names.
    The mocked resolver emulates that acceptance deterministically (real glibc
    behaviour; musl/macOS resolvers differ, which is why it is mocked)."""

    def fake_getaddrinfo(h, port, *args, **kwargs):
        if h in ("2130706433", "0x7f000001", "127.1"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port or 0))]
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(validator.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="Blocked IP"):
        await resolve_and_validate(host)


@pytest.mark.asyncio
async def test_resolve_allows_public_resolution(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]

    monkeypatch.setattr(validator.socket, "getaddrinfo", fake_getaddrinfo)
    await resolve_and_validate("example.com")  # must NOT raise


@pytest.mark.asyncio
async def test_resolve_blocks_dns_failure():
    with pytest.raises(ValueError, match="DNS resolution failed"):
        await resolve_and_validate("no-such-host.invalid")


# ---- redirects must never be followed ----------------------------------------

@pytest.mark.asyncio
async def test_client_factory_never_follows_redirects():
    """Both proxy call sites build their client through this factory; a 302 to a
    private IP is RETURNED (3xx status visible upstream of us), never chased."""
    factory = ssrf_safe_client_factory(timeout_seconds=2.0)
    client = factory(headers={"irrelevant": "ignored-by-design"}, timeout=99)
    try:
        assert client.follow_redirects is False
        assert client.timeout.connect == 2.0  # our timeout, not the SDK's
    finally:
        await client.aclose()
