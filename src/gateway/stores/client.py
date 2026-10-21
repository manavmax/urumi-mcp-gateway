"""Gateway-side client for the provisioner (Phase 5, ADR-060).

The gateway enforces roles and quotas, THEN asks the provisioner to do the
cluster work. All calls carry the shared internal token (provisioner-token
Secret) in X-Provisioner-Token; the token is never logged. Failures return a
safe reason string, never the raw error body.
"""

from __future__ import annotations

import logging

import httpx
from config import get_settings

logger = logging.getLogger("gateway.provisioner")


class ProvisionerError(RuntimeError):
    """The provisioner call failed; .status carries the HTTP status (0 for
    transport errors). The message is safe to store as failure_reason."""


async def _client() -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(
        base_url=s.provisioner_url,
        headers={"X-Provisioner-Token": s.provisioner_token or ""},
        timeout=30,
    )


async def provision_store(slug: str) -> None:
    """Ask the provisioner to start provisioning. Idempotent (202 either way).
    Raises ProvisionerError on refusal/failure."""
    try:
        async with await _client() as c:
            r = await c.post("/v1/stores", json={"slug": slug})
        if r.status_code == 202:
            return
        raise ProvisionerError(f"provisioner refused: {r.status_code}")
    except httpx.HTTPError as exc:
        logger.warning("provisioner unreachable: %s", exc.__class__.__name__)
        raise ProvisionerError("provisioner unreachable") from exc


async def deprovision_store(slug: str) -> None:
    try:
        async with await _client() as c:
            r = await c.delete(f"/v1/stores/{slug}")
        if r.status_code == 202:
            return
        raise ProvisionerError(f"provisioner refused: {r.status_code}")
    except httpx.HTTPError as exc:
        logger.warning("provisioner unreachable: %s", exc.__class__.__name__)
        raise ProvisionerError("provisioner unreachable") from exc


async def store_state(slug: str) -> dict | None:
    """{phase, reason} | None when the provisioner is unreachable or the store
    is unknown (phase 'gone')."""
    try:
        async with await _client() as c:
            r = await c.get(f"/v1/stores/{slug}")
        if r.status_code == 200:
            body = r.json()
            return {"phase": body.get("phase", ""), "reason": (body.get("reason") or "")[:300]}
        if r.status_code == 404:
            return None
        raise ProvisionerError(f"provisioner status failed: {r.status_code}")
    except httpx.HTTPError as exc:
        logger.warning("provisioner unreachable: %s", exc.__class__.__name__)
        return None
