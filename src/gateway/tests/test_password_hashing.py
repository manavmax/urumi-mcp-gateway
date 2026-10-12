"""Password hashing + verification contract (docs/04 §4).

User passwords are argon2id (salted, memory-hard, constant-time verify via argon2-cffi).
These tests pin the behavioural contract: the right password verifies; a wrong,
tampered or garbage hash fails *without raising*; hashes are never reproducible
(per-hash random salt); and the sha256 lookup column is not itself a usable password.
"""

from __future__ import annotations

import hashlib

import pytest

from auth.rbac import hash_password, verify_password
from auth.keys import _sha256, generate_raw_key, hash_key, verify_hash



async def test_hash_is_argon2id_with_random_salt():
    h1 = await hash_password("correct horse battery staple")
    h2 = await hash_password("correct horse battery staple")
    assert h1.startswith("$argon2id$"), h1[:12]
    # same password hashed twice -> different salts, so no rainbow-table reuse
    assert h1 != h2


async def test_verify_accepts_only_the_right_password():
    h = await hash_password("hunter2-«secret»")
    assert await verify_password(h, "hunter2-«secret»") is True
    assert await verify_password(h, "Hunter2-«secret»") is False  # case differs
    assert await verify_password(h, "") is False


async def test_verify_returns_false_for_tampered_hash():
    h = await hash_password("s3cret")
    tampered = h[:-1] + ("A" if h[-1] != "A" else "B")
    assert tampered != h
    assert await verify_password(tampered, "s3cret") is False


async def test_verify_never_raises_on_garbage_hashes():
    for bad in ["", "not-a-hash", "$argon2id$garbage", "plaintext"]:
        assert await verify_password(bad, "whatever") is False


async def test_sha256_lookup_hash_is_not_a_working_password():
    """The ApiKey.sha256 column exists for O(1) lookup; it must never verify as the
    credential itself (that check is argon2id's job, via verify_hash)."""
    raw = generate_raw_key()
    sha = _sha256(raw)
    assert len(sha) == 64 and sha == hashlib.sha256(raw.encode()).hexdigest()
    assert await verify_password(sha, raw) is False


def test_api_key_generate_hash_verify_roundtrip():
    raw = generate_raw_key()
    assert raw.startswith("urumi_sk_")
    assert len(raw) >= 43  # 32 urlsafe bytes + prefix
    h = hash_key(raw)
    assert h.startswith("$argon2id$")
    assert verify_hash(h, raw) is True
    assert verify_hash(h, raw + "x") is False
    assert verify_hash("garbage", raw) is False
    assert verify_hash(h, raw + " ") is False  # no silent strip-in-verify path


def test_raw_key_is_256bit_entropy_sha256_lookup_is_deterministic():
    k1, k2 = generate_raw_key(), generate_raw_key()
    assert k1 != k2 and _sha256(k1) != _sha256(k2)
    assert _sha256(k1) == _sha256(k1)  # stable lookup key
