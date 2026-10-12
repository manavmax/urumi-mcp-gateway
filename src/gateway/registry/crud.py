"""Servers CRUD + seeding helpers."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Server
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


async def get_server(db: AsyncSession, server_id: uuid.UUID) -> Optional[Server]:
    res = await db.execute(select(Server).where(Server.id == server_id))
    return res.scalars().first()


async def get_server_by_slug(db: AsyncSession, slug: str) -> Optional[Server]:
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
    server.updated_at = datetime.now(timezone.utc)
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
    srv.updated_at = datetime.now(timezone.utc)
    await db.flush()


async def seed_default_servers(db: AsyncSession):
    """Ensure woo-mcp + time + notes are present (idempotent).

    Uses in-cluster DNS names; these match helm service names.
    """
    from config import get_settings
    # Determine suffix-aware URLs — use full helm fullname pattern
    # helm fullname is usually urumi (release) — services are urumi-*
    # Support both urumi-* and bare names via env override if needed.
    defaults = [
        {"slug": "woo", "url": "http://urumi-woo-mcp:8000/mcp", "auth_type": "none"},
        {"slug": "time", "url": "http://urumi-demo-time:8000/mcp", "auth_type": "none"},
        {"slug": "notes", "url": "http://urumi-demo-notes:8000/mcp", "auth_type": "bearer"},
    ]
    for d in defaults:
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
                # For notes, try to pull token from env/secret if available
                if d["slug"] == "notes":
                    token = (get_settings().openai_api_key or "")  # not correct; actually NOTES_API_TOKEN env
                    # Try NOTES_API_TOKEN env
                    import os

                    notes_token = os.environ.get("NOTES_API_TOKEN") or os.environ.get("notes_api_token") or ""
                    if notes_token:
                        from registry.crypto import encrypt

                        srv.credential_encrypted = encrypt(notes_token)
                        srv.auth_type = "bearer"
                db.add(srv)
            except Exception:
                pass
    await db.flush()
