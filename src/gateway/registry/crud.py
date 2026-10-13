"""Servers CRUD + seeding helpers."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from db.models import Server
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.crypto import encrypt
from registry.validator import validate_url

SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _validate_slug(slug: str):
    if not slug or not SLUG_RE.match(slug):
        raise ValueError("slug must match ^[a-z0-9-]+$")


async def list_servers(db: AsyncSession, include_disabled: bool = True) -> list[Server]:
    q = select(Server).order_by(Server.slug)
    if not include_disabled:
        q = q.where(Server.enabled.is_(True))
    res = await db.execute(q)
    return list(res.scalars().all())


async def get_server(db: AsyncSession, server_id: uuid.UUID) -> Server | None:
    res = await db.execute(select(Server).where(Server.id == server_id))
    return res.scalars().first()


async def get_server_by_slug(db: AsyncSession, slug: str) -> Server | None:
    res = await db.execute(select(Server).where(Server.slug == slug))
    return res.scalars().first()


async def create_server(
    db: AsyncSession,
    *,
    slug: str,
    url: str,
    auth_type: str = "none",
    header_name: str | None = None,
    credential: str | None = None,
    timeout_ms: int = 10000,
    enabled: bool = True,
    allowed_host_suffixes: list[str] | None = None,
    allowed_domains: list[str] | None = None,
) -> Server:
    slug = slug.strip().lower()
    _validate_slug(slug)
    validate_url(url, allowed_host_suffixes=allowed_host_suffixes, allowed_domains=allowed_domains)
    if auth_type not in ("none", "bearer", "header"):
        raise ValueError("auth_type must be none|bearer|header")
    if auth_type == "header" and not (header_name or "").strip():
        raise ValueError("header_name required when auth_type=header")
    # unique slug check
    existing = await get_server_by_slug(db, slug)
    if existing:
        raise ValueError(f"slug '{slug}' already exists")

    enc = encrypt(credential) if credential else None
    srv = Server(
        slug=slug,
        url=url.strip(),
        auth_type=auth_type,
        header_name=(header_name.strip() if header_name else None),
        credential_encrypted=enc,
        enabled=enabled,
        status="Unknown",
        timeout_ms=timeout_ms,
    )
    db.add(srv)
    await db.flush()
    return srv


async def update_server(
    db: AsyncSession,
    server: Server,
    *,
    slug: str | None = None,
    url: str | None = None,
    auth_type: str | None = None,
    header_name: str | None = None,
    credential: str | None = None,
    timeout_ms: int | None = None,
    enabled: bool | None = None,
    allowed_host_suffixes: list[str] | None = None,
    allowed_domains: list[str] | None = None,
) -> Server:
    if slug is not None:
        slug = slug.strip().lower()
        _validate_slug(slug)
        if slug != server.slug:
            dup = await get_server_by_slug(db, slug)
            if dup:
                raise ValueError(f"slug '{slug}' already exists")
            server.slug = slug
    if url is not None:
        validate_url(url, allowed_host_suffixes=allowed_host_suffixes, allowed_domains=allowed_domains)
        server.url = url.strip()
    if auth_type is not None:
        if auth_type not in ("none", "bearer", "header"):
            raise ValueError("auth_type must be none|bearer|header")
        server.auth_type = auth_type
    if header_name is not None:
        server.header_name = header_name.strip() or None
    if credential is not None:
        # empty string means clear; non-empty encrypt
        server.credential_encrypted = encrypt(credential) if credential else None
    if timeout_ms is not None:
        server.timeout_ms = int(timeout_ms)
    if enabled is not None:
        server.enabled = bool(enabled)
    server.updated_at = datetime.now(UTC)
    await db.flush()
    return server


async def delete_server(db: AsyncSession, server: Server):
    # also delete cached tools (FK cascade handles it, but clean)
    await db.delete(server)
    await db.flush()


async def set_server_status(db: AsyncSession, server_id: uuid.UUID, status: str, last_error: str | None = None):
    srv = await get_server(db, server_id)
    if not srv:
        return
    srv.status = status
    srv.last_error = last_error
    srv.updated_at = datetime.now(UTC)
    await db.flush()


INTERNAL_DEFAULTS = [
    {"slug": "woo", "url": "http://urumi-woo-mcp:8000/mcp", "auth_type": "none"},
    {"slug": "time", "url": "http://urumi-demo-time:8000/mcp", "auth_type": "none"},
    {"slug": "notes", "url": "http://urumi-demo-notes:8000/mcp", "auth_type": "bearer"},
]


async def seed_default_servers(db: AsyncSession):
    """Ensure woo-mcp + time + notes are present (idempotent).

    Uses in-cluster DNS names; these match helm service names. Credentials are NOT
    seeded here: `resync_internal_credentials` applies the Secret/env value (encrypted
    with the CURRENT Fernet key) on every start, so a rotated Secret or key self-heals.
    """
    for d in INTERNAL_DEFAULTS:
        existing = await get_server_by_slug(db, d["slug"])
        if not existing:
            try:
                srv = Server(
                    slug=d["slug"],
                    url=d["url"],
                    auth_type=d["auth_type"],
                    header_name=None,
                    credential_encrypted=None,
                    enabled=True,
                    status="Unknown",
                    timeout_ms=10000,
                )
                db.add(srv)
            except Exception:
                pass
    await db.flush()


async def resync_internal_credentials(db: AsyncSession) -> list[str]:
    """Re-apply the Secret/env credentials to the SEEDED internal servers (idempotent).

    The seeded upstreams (woo/time/notes) are authoritative: their credential comes from
    the environment/Secret, encrypted with the CURRENT Fernet key. A stored value that
    was encrypted under a different key, or a Secret that rotated, is re-encrypted here
    on start instead of failing every tool call with "failed to decrypt credential (key
    mismatch)" - the drift an accidental `helm template | kubectl apply` causes
    (docs/DECISIONS.md ADR-026). Servers an admin added (any slug outside the seed list)
    are never touched, and the caller logs the slug only, never the value.

    Returns the slugs whose stored credential changed.
    """
    import os

    # lower-case is the pydantic field name, kept as a fallback alias on purpose
    notes_token = os.environ.get("NOTES_API_TOKEN") or os.environ.get("notes_api_token") or ""  # noqa: SIM112
    desired = {d["slug"]: (notes_token if d["slug"] == "notes" else "") for d in INTERNAL_DEFAULTS}

    resynced: list[str] = []
    for slug, want in desired.items():
        if not want:
            # nothing in the environment to enforce (or the server takes no auth):
            # leave whatever is stored alone.
            continue
        srv = await get_server_by_slug(db, slug)
        if not srv:
            continue  # seeding runs first; a missing row is not a credential problem
        if await _assure_credential(srv, want):
            resynced.append(srv.slug)
    if resynced:
        await db.flush()
    return resynced


async def _assure_credential(srv: Server, want: str) -> bool:
    """Make srv's stored credential decrypt to `want` under the current key.

    Returns True when the row changed (the caller flushes and logs the slug only).
    """
    from registry.crypto import decrypt

    current = None
    if srv.credential_encrypted:
        try:
            current = decrypt(srv.credential_encrypted)
        except ValueError:
            current = None  # encrypted under a different key: re-encrypt below
    if (current or None) == (want or None):
        return False  # already the Secret's value under the current key: no churn
    srv.credential_encrypted = encrypt(want) if want else None
    if want:
        srv.auth_type = "bearer"
    srv.updated_at = datetime.now(UTC)
    return True
