"""Dashboard session: signed cookie + CSRF.

Cookie value is an itsdangerous TimestampSigner payload: {"uid": str, "csrf": str}
Separate from gateway /mcp API keys (docs/05 §1.3).
"""

from __future__ import annotations

import secrets
import uuid

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner, URLSafeTimedSerializer
from fastapi import Request, Response

from config import get_settings


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().effective_session_secret, salt="urumi-session")


def _signer() -> TimestampSigner:
    # kept for max_age validation via serializer
    return TimestampSigner(get_settings().effective_session_secret, salt="urumi-session")


def create_session_cookie(user_id: uuid.UUID) -> tuple[str, str]:
    """Return (cookie_value, csrf_token)."""
    csrf = secrets.token_urlsafe(24)
    payload = {"uid": str(user_id), "csrf": csrf}
    ser = _serializer()
    token = ser.dumps(payload)
    return token, csrf


def verify_session_cookie(token: str) -> dict | None:
    if not token:
        return None
    ser = _serializer()
    max_age = get_settings().session_max_age_seconds
    try:
        data = ser.loads(token, max_age=max_age)
        if not isinstance(data, dict) or "uid" not in data or "csrf" not in data:
            return None
        return data
    except (BadSignature, SignatureExpired):
        return None
    except Exception:
        return None


def set_session_cookie(response: Response, cookie_value: str):
    s = get_settings()
    response.set_cookie(
        key=s.session_cookie_name,
        value=cookie_value,
        max_age=s.session_max_age_seconds,
        httponly=True,
        secure=False,  # true in prod when TLS; keep false for kind nip.io http
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response):
    s = get_settings()
    response.delete_cookie(key=s.session_cookie_name, path="/")
