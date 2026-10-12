"""RBAC / auth dependencies for FastAPI routes."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, User
from db.session import get_db
from auth.keys import verify_api_key
from auth.session import verify_session_cookie


async def get_current_user_via_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """For /mcp: Bearer key. Populates request.state for audit."""
    auth = request.headers.get("authorization", "") or request.headers.get("Authorization", "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.headers.get("x-api-key", "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    res = await verify_api_key(db, token)
    if not res:
        raise HTTPException(status_code=401, detail="invalid or revoked key")
    user, key = res
    # stash for audit + downstream
    request.state.api_key_id = key.id
    request.state.api_key_last4 = key.last4
    request.state.current_user = user
    return user


async def get_current_user_via_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """For /api/* dashboard: session cookie."""
    from config import get_settings

    cookie_name = get_settings().session_cookie_name
    token = request.cookies.get(cookie_name, "")
    data = verify_session_cookie(token)
    if not data:
        raise HTTPException(status_code=401, detail="not authenticated")
    try:
        uid = uuid.UUID(data["uid"])
    except Exception:
        raise HTTPException(status_code=401, detail="invalid session")
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalars().first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="user not found or inactive")
    request.state.current_user = user
    request.state.session_csrf = data.get("csrf", "")
    return user


def require_admin(user: User = Depends(get_current_user_via_session)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    return user


def require_member(user: User = Depends(get_current_user_via_session)) -> User:
    # both admin and member pass; admin is a superset
    if user.role not in ("admin", "member"):
        raise HTTPException(status_code=403, detail="forbidden")
    return user


async def get_optional_session_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Try session, return None if absent (for mixed routes)."""
    try:
        return await get_current_user_via_session(request, db)
    except HTTPException:
        return None


def verify_csrf(request: Request):
    """Call inside mutating /api handlers that use session auth."""
    expected = getattr(request.state, "session_csrf", None)
    if expected is None:
        # try to re-derive from cookie if dependency not run
        from config import get_settings

        token = request.cookies.get(get_settings().session_cookie_name, "")
        data = verify_session_cookie(token)
        expected = (data or {}).get("csrf", "")
    got = request.headers.get("x-csrf-token", "") or request.headers.get("X-CSRF-Token", "")
    if not expected or not got or got != expected:
        raise HTTPException(status_code=403, detail="csrf validation failed")


async def hash_password(password: str) -> str:
    from argon2 import PasswordHasher

    ph = PasswordHasher()
    return ph.hash(password)


async def verify_password(hash_: str, password: str) -> bool:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    ph = PasswordHasher()
    try:
        return ph.verify(hash_, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False
