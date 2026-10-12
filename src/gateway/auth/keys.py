"""API key generation / hashing / verification.

Brief (docs/04 §4): the raw key is shown once; the database stores ONLY the SHA-256 hex
digest of the raw key (64 chars), looked up by that digest and compared with
hmac.compare_digest. No slow KDF on this path: the raw key is 256 bits of uniform
randomness (secrets.token_urlsafe(32)), so there is nothing to brute-force and an
argon2id check would only cost latency on every /mcp call. User passwords keep argon2id
(docs/DECISIONS.md ADR-024 superseded by ADR-025).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, User

PREFIX = "urumi_sk_"


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_raw_key() -> str:
    return f"{PREFIX}{secrets.token_urlsafe(32)}"


def hash_key(raw: str) -> str:
    """The ONLY credential material stored for an API key: 64 lowercase hex chars."""
    return _sha256(raw)


async def create_api_key(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    expires_at: datetime | None = None,
) -> tuple[ApiKey, str]:
    """Create an ApiKey row; return (row, raw_key). raw_key is shown once, never stored."""
    raw = generate_raw_key()
    sha = _sha256(raw)
    last4 = raw[-4:]
    row = ApiKey(
        user_id=user_id,
        prefix=PREFIX,
        sha256=sha,
        last4=last4,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return row, raw


async def verify_api_key(db: AsyncSession, raw: str) -> tuple[User, ApiKey] | None:
    """Look the raw key up by its sha256 digest, compare digests in constant time, then
    apply revoked/expiry checks. Returns (user, key) or None — never raises."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    sha = _sha256(raw)
    result = await db.execute(select(ApiKey).where(ApiKey.sha256 == sha))
    key_row = result.scalars().first()
    if not key_row:
        return None
    # constant-time comparison of the hex digests (defense in depth on top of the
    # indexed equality lookup - the lookup found the row, the compare confirms it)
    if not hmac.compare_digest(key_row.sha256, sha):
        return None
    if key_row.revoked_at is not None:
        return None
    if key_row.expires_at is not None:
        # compare aware
        from datetime import datetime as _dt

        now = datetime.now(timezone.utc)
        exp = key_row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            return None
    # fetch user
    ures = await db.execute(select(User).where(User.id == key_row.user_id))
    user = ures.scalars().first()
    if not user or not user.is_active:
        return None
    return user, key_row


async def revoke_api_key(db: AsyncSession, key_id: uuid.UUID) -> bool:
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    row = result.scalars().first()
    if not row:
        return False
    if row.revoked_at is not None:
        return True
    row.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    return True
