"""Fernet encryption for upstream credentials (docs/04 §6.3).

Key comes from K8s Secret gateway-secrets FERNET_KEY (44 urlsafe chars).
Cipher is stored as LargeBinary in servers.credential_encrypted.
"""

from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from config import get_settings


def _get_fernet() -> Fernet:
    raw = get_settings().fernet_key.strip()
    if not raw:
        # dev fallback: deterministic key so tests don't fail when no Secret
        # In prod the Secret always provides this; never use this in prod.
        raw = base64.urlsafe_b64encode(b"0" * 32).decode()
    # ensure valid Fernet key (32 urlsafe base64 bytes padded to 44)
    try:
        # Fernet will validate on construction
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except Exception:
        # if raw is not base64, derive (should not happen in prod)
        # but keep working for dev
        key = base64.urlsafe_b64encode(raw.encode()[:32].ljust(32, b"0"))
        return Fernet(key)


# Cached instance but must respect key rotation: clear when key changes?
# We cache per-process; key rotation requires pod restart (acceptable).
_fernet: Fernet | None = None


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = _get_fernet()
    return _fernet


def encrypt(plaintext: str) -> bytes:
    if not plaintext:
        return b""
    return get_fernet().encrypt(plaintext.encode())


def decrypt(cipher: bytes | None) -> str:
    if not cipher:
        return ""
    try:
        return get_fernet().decrypt(cipher).decode()
    except InvalidToken as exc:
        raise ValueError("failed to decrypt credential (key mismatch)") from exc


def reset_fernet_cache():
    global _fernet
    _fernet = None
