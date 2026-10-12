"""API key generation / hashing / verification.

Docs/04 §4: raw key shown once, stored as argon2id hash + sha256 lookup column.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, User

PREFIX = "urumi_sk_"
_ph = PasswordHasher()

# Backward compat: some callers import ph
ph = _ph


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_raw_key() -> str:
    return f"{PREFIX}{secrets.token_urlsafe(32)}"


def hash_key(raw: str) -> str:
    return _ph.hash(raw)


def verify_hash(stored_hash: str, raw: str) -> bool:
    try:
        return _ph.verify(stored_hash, raw)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


async def create_api_key(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    expires_at: datetime | None = None,
) -> tuple[ApiKey, str]:
    """Create an ApiKey row; return (row, raw_key). raw_key is shown once."""
    raw = generate_raw_key()
    sha = _sha256(raw)
    hashed = hash_key(raw)
    last4 = raw[-4:]
    row = ApiKey(
        user_id=user_id,
        prefix=PREFIX,
        hash=hashed,
        sha256=sha,
        last4=last4,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return row, raw


async def verify_api_key(db: AsyncSession, raw: str) -> tuple[User, ApiKey] | None:
    """Lookup by sha256 + verify argon2. Returns (user, key) or None."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    sha = _sha256(raw)
    result = await db.execute(select(ApiKey).where(ApiKey.sha256 == sha))
    key_row = result.scalars().first()
    if not key_row:
        return None
    if key_row.revoked_at is not None:
        return None
    if key_row.expires_at is not None:
        # compare aware
        now = datetime.now(timezone.utc)
        exp = key_row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            return None
    if not verify_hash(key_row.hash, raw):
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
