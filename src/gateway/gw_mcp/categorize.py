"""Map upstream failures to a safe, stable error category (observability item 1).

Categories (docs/11_OBSERVABILITY.md):
  connection_refused, timeout, dns_failure, tls_error, http_error (with status
  code), invalid_response, auth_rejected, other.

Only the category string is ever stored or returned - never raw exception text, never
a URL with credentials, never headers or tokens. The human label is derived from the
category, so no exception message (which could contain a secret) is ever persisted.
"""

from __future__ import annotations

import asyncio
import errno as _errno
import json
import socket
import ssl

import httpx

CATEGORY_TIMEOUT = "timeout"
CATEGORY_CONNECTION_REFUSED = "connection_refused"
CATEGORY_DNS_FAILURE = "dns_failure"
CATEGORY_TLS_ERROR = "tls_error"
CATEGORY_HTTP_ERROR = "http_error"  # always suffixed with the status code: http_error:502
CATEGORY_INVALID_RESPONSE = "invalid_response"
CATEGORY_AUTH_REJECTED = "auth_rejected"
CATEGORY_OTHER = "other"

# Human-safe label for each category; this safe label is what server.last_error holds.
_CATEGORY_LABELS = {
    CATEGORY_CONNECTION_REFUSED: "connection refused",
    CATEGORY_TIMEOUT: "timeout",
    CATEGORY_DNS_FAILURE: "dns failure",
    CATEGORY_TLS_ERROR: "tls error",
    CATEGORY_INVALID_RESPONSE: "invalid response",
    CATEGORY_AUTH_REJECTED: "auth rejected",
    CATEGORY_OTHER: "upstream error",
}

# HTTP statuses that mean the upstream rejected our credentials (never store the
# reason body - only this category).
_AUTH_STATUSES = {401, 403}


def category_label(category: str | None) -> str | None:
    """Safe human label for a stored category (strips any http_error:<code> suffix)."""
    if not category:
        return None
    base = category.split(":", 1)[0]
    return _CATEGORY_LABELS.get(base, "upstream error")


def _status_code_from_exc(exc: BaseException) -> int | None:
    """Pull a status code out of an exception chain (httpx or MCP SDK wrappers)."""
    seen = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, httpx.HTTPStatusError) and getattr(cur, "response", None) is not None:
            return cur.response.status_code
        if isinstance(cur, httpx.Response) and getattr(cur, "status_code", None):
            return cur.status_code
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
    return None


def _causes(exc: BaseException) -> list[BaseException]:
    """The exception and its __cause__/__context__ chain, root-first."""
    out: list[BaseException] = []
    seen = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        out.append(cur)
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
    return out


def classify(exc: BaseException) -> str:
    """Return a stable category string for an upstream failure. Never raises.

    Handles httpx transport errors, MCP SDK wrappers and JSON/parse failures. The
    returned value is the category token (http_error carries `:code`).
    """
    status = _status_code_from_exc(exc)
    if status in _AUTH_STATUSES:
        return CATEGORY_AUTH_REJECTED
    if status is not None:
        return f"{CATEGORY_HTTP_ERROR}:{status}"

    chain = _causes(exc)
    for e in chain:
        if isinstance(e, (asyncio.TimeoutError, httpx.TimeoutException)):
            return CATEGORY_TIMEOUT
        if isinstance(e, socket.gaierror):
            return CATEGORY_DNS_FAILURE
        if isinstance(e, ssl.SSLError):
            return CATEGORY_TLS_ERROR
        if isinstance(e, ConnectionRefusedError) or (isinstance(e, OSError) and getattr(e, "errno", None) == _errno.ECONNREFUSED):
            return CATEGORY_CONNECTION_REFUSED
        if isinstance(e, httpx.ConnectError):
            # deep cause already examined above; a bare ConnectError with no
            # recognizable cause is treated as connection_refused (the common case)
            return CATEGORY_CONNECTION_REFUSED
        if isinstance(e, (json.JSONDecodeError, ValueError)):
            return CATEGORY_INVALID_RESPONSE

    # an exception that made it here with no recognisable cause is "other"
    return CATEGORY_OTHER
