"""API key storage contract (docs/04 §4, ADR-025).

The database stores ONLY the sha256 hex digest of the raw key (64 chars); authentication
is an indexed lookup by that digest plus hmac.compare_digest, then revoked/expiry checks.
The raw key (256-bit random) is shown once and never stored. There is deliberately NO
slow KDF here: a 2^256 key space has nothing to brute-force, and a slow hash would tax
every /mcp call. Revocation must take effect on the very next call.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from auth.keys import PREFIX, create_api_key, generate_raw_key, hash_key, revoke_api_key, verify_api_key
from db.models import ApiKey, User

from tests.conftest import FakeResult

# every column an ApiKey row may have - and none of them can hold the raw key
# (rate_limit_per_minute is the ADR-057 admin override: a small int, not a secret)
SAFE_KEY_COLUMNS = {"id", "user_id", "prefix", "sha256", "last4", "revoked_at", "expires_at", "rate_limit_per_minute", "created_at"}


def now():
    return datetime.now(UTC)


def _user(*, active=True) -> User:
    u = User(email="member@example.com", password_hash="x", role="member", is_active=active)
    u.id = uuid.uuid4()
    return u


def _key(*, raw=None, user_id=None, revoked_at=None, expires_at=None):
    raw = raw or generate_raw_key()
    row = ApiKey(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        prefix=PREFIX,
        sha256=hash_key(raw),
        last4=raw[-4:],
        revoked_at=revoked_at,
        expires_at=expires_at,
    )
    return row, raw


class _AuthDB:
    """Fake AsyncSession for verify_api_key: answers the digest lookup + owner fetch.

    With honest_index=True the sha256 query only returns rows whose stored digest matches
    (like the real unique index); with honest_index=False it surfaces a row for ANY digest
    so the hmac.compare_digest step inside verify_api_key is genuinely exercised.
    """

    def __init__(self, keys=(), user=None, honest_index=True):
        self.keys = list(keys)
        self.user = user
        self.honest_index = honest_index

    async def execute(self, stmt):
        value = stmt.whereclause.right.value
        if isinstance(value, str):  # select(ApiKey).where(ApiKey.sha256 == X)
            row = next((k for k in self.keys if k.sha256 == value), None)
            if row is None and self.keys and not self.honest_index:
                row = self.keys[0]
            return FakeResult(row)
        key = next((k for k in self.keys if k.id == value), None)
        if key is not None:  # select(ApiKey).where(ApiKey.id == X) from revoke_api_key
            return FakeResult(key)
        if self.user is not None and self.user.id == value:
            return FakeResult(self.user)
        return FakeResult(None)

    def add(self, obj):
        pass

    async def flush(self):
        return None


# ---- storage: sha256 only, raw key never stored ----

def test_stored_hash_is_sha256_hex_and_the_only_credential_column():
    raw = generate_raw_key()
    sha = hash_key(raw)
    assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
    assert sha == hashlib.sha256(raw.encode()).hexdigest()  # plain sha256, no KDF
    assert "hash" not in ApiKey.__table__.columns, "the argon2 column must be gone"
    assert {c.name for c in ApiKey.__table__.columns} <= SAFE_KEY_COLUMNS, "no column may hold the raw key"
    assert raw not in sha


def test_digest_is_deterministic_and_collision_free():
    k1, k2 = generate_raw_key(), generate_raw_key()
    assert k1 != k2 and len(k1) >= 43 and k1.startswith(PREFIX)
    assert hash_key(k1) != hash_key(k2)
    assert hash_key(k1) == hash_key(k1)  # deterministic -> usable as the lookup key


async def test_key_shown_once_and_never_stored():
    row, raw = await create_api_key(_AuthDB(), uuid.uuid4())
    assert row.sha256 == hashlib.sha256(raw.encode()).hexdigest()
    assert row.last4 == raw[-4:] and raw.startswith(PREFIX) and len(raw) >= 43
    stored = {c.name: str(getattr(row, c.name)) for c in ApiKey.__table__.columns}
    assert raw not in json.dumps(stored), "the raw key is shown once and never persisted"
    assert row.revoked_at is None and row.expires_at is None


async def test_recreate_uses_a_fresh_digest():
    db = _AuthDB()
    row1, raw1 = await create_api_key(db, uuid.uuid4())
    row2, raw2 = await create_api_key(db, uuid.uuid4())
    assert raw1 != raw2 and row1.sha256 != row2.sha256
    # a recreated key cannot authenticate under the old digest
    assert await verify_api_key(_AuthDB(keys=[row2], user=_user()), raw1) is None


async def test_authenticates_a_valid_key():
    user = _user()
    row, raw = _key(user_id=user.id)
    db = _AuthDB(keys=[row], user=user)
    res = await verify_api_key(db, raw)
    assert res is not None
    assert res[0].id == user.id and res[1].sha256 == row.sha256


async def test_verify_fails_closed():
    user = _user()
    row, _raw = _key(user_id=user.id)
    db = _AuthDB(keys=[row], user=user)
    # empty / whitespace-only keys are rejected before any lookup
    assert await verify_api_key(db, "") is None
    assert await verify_api_key(db, "   ") is None
    # a raw key with no matching row is rejected
    assert await verify_api_key(_AuthDB(keys=[row], user=user), generate_raw_key()) is None
    # a tampered stored digest must not authenticate: compare_digest fails closed
    assert await verify_api_key(_AuthDB(keys=[row], user=user, honest_index=False), generate_raw_key()) is None
    # an inactive owner's key is dead even with a matching digest
    dead_owner_key, dead_raw = _key()
    assert await verify_api_key(_AuthDB(keys=[dead_owner_key], user=_user(active=False)), dead_raw) is None


async def test_revocation_takes_effect_on_the_next_call():
    user = _user()
    row, raw = _key(user_id=user.id)
    db = _AuthDB(keys=[row], user=user)
    assert await verify_api_key(db, raw) is not None  # works before revocation
    assert await revoke_api_key(db, row.id) is True
    assert row.revoked_at is not None
    assert await verify_api_key(db, raw) is None  # the next call is unauthenticated
    # revoking an already-revoked key is a no-op success
    assert await revoke_api_key(db, row.id) is True


async def test_expired_key_is_rejected_but_future_expiry_works():
    user = _user()
    row, raw = _key(user_id=user.id)
    row.expires_at = now() - timedelta(hours=1)
    db = _AuthDB(keys=[row], user=user)
    assert await verify_api_key(db, raw) is None
    row.expires_at = now() + timedelta(hours=1)
    assert await verify_api_key(db, raw) is not None

