"""User password hashing + verification contract (docs/04 §4).

User passwords are argon2id (salted, memory-hard, constant-time verify via argon2-cffi).
These tests pin the behavioural contract: the right password verifies; a wrong,
tampered or garbage hash fails *without raising*; hashes are never reproducible
(per-hash random salt). API keys are deliberately different - see test_api_keys.py.
"""

from __future__ import annotations

from auth.rbac import hash_password, verify_password


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
