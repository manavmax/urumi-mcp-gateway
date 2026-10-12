"""Users + API keys routes (/api/users, /api/keys, /api/auth)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, User
from db.session import get_db
from auth.rbac import (
    get_current_user_via_session,
    require_admin,
    verify_csrf,
    hash_password,
    verify_password,
)
from auth.session import create_session_cookie, verify_session_cookie, set_session_cookie, clear_session_cookie
from auth.keys import create_api_key, revoke_api_key
from config import get_settings

router = APIRouter(tags=["users"])


class LoginBody(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)
    role: str = Field(pattern=r"^(admin|member)$")


class KeyCreate(BaseModel):
    expires_at: Optional[str] = None  # ISO8601


@router.post("/api/auth/login")
async def login(body: LoginBody, response: Response, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    res = await db.execute(select(User).where(User.email == email))
    user = res.scalars().first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="invalid credentials")
    if not await verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    cookie_val, csrf = create_session_cookie(user.id)
    set_session_cookie(response, cookie_val)
    return {"user": {"id": str(user.id), "email": user.email, "role": user.role}, "csrf_token": csrf}


@router.post("/api/auth/logout")
async def logout(response: Response, request: Request):
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/api/me")
async def me(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user_via_session)):
    csrf = getattr(request.state, "session_csrf", "")
    if not csrf:
        token = request.cookies.get(get_settings().session_cookie_name, "")
        data = verify_session_cookie(token)
        csrf = (data or {}).get("csrf", "")
    return {"user": {"id": str(user.id), "email": user.email, "role": user.role}, "csrf_token": csrf}


@router.get("/api/users")
async def list_users(db: AsyncSession = Depends(get_db), user=Depends(require_admin)):
    res = await db.execute(select(User).order_by(User.created_at))
    rows = res.scalars().all()
    return {"users": [{"id": str(r.id), "email": r.email, "role": r.role, "is_active": r.is_active, "created_at": r.created_at.isoformat()} for r in rows]}


@router.post("/api/users", status_code=201)
async def create_user(body: UserCreate, request: Request, db: AsyncSession = Depends(get_db), user=Depends(require_admin)):
    verify_csrf(request)
    email = body.email.strip().lower()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="email already exists")
    pw_hash = await hash_password(body.password)
    u = User(email=email, password_hash=pw_hash, role=body.role)
    db.add(u)
    await db.flush()
    await db.commit()
    return {"id": str(u.id), "email": u.email, "role": u.role}


@router.delete("/api/users/{user_id}", status_code=204)
async def delete_user(user_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), admin=Depends(require_admin)):
    verify_csrf(request)
    res = await db.execute(select(User).where(User.id == user_id))
    u = res.scalars().first()
    if not u:
        raise HTTPException(status_code=404, detail="user not found")
    if u.id == admin.id:
        raise HTTPException(status_code=400, detail="cannot delete self")
    await db.delete(u)
    await db.commit()
    return None


@router.get("/api/keys")
async def list_keys(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user_via_session)):
    # Admin sees all; member sees own
    if user.role == "admin":
        # if ?user_id= filter?
        q = select(ApiKey).order_by(ApiKey.created_at.desc())
        res = await db.execute(q)
    else:
        res = await db.execute(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc()))
    rows = res.scalars().all()
    # mask: only show last4 + prefix
    return {
        "keys": [
            {
                "id": str(r.id),
                "user_id": str(r.user_id),
                "prefix": r.prefix,
                "last4": r.last4,
                "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/api/keys", status_code=201)
async def create_key(body: KeyCreate, request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user_via_session)):
    verify_csrf(request)
    # body may contain user_id for admin creating for another user
    # For now, always for current user; admin can specify via query param
    # Support optional user_id in body for admin
    target_user_id = user.id
    try:
        # check raw body for user_id
        raw = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        raw = {}
    if isinstance(raw, dict) and "user_id" in raw and user.role == "admin":
        try:
            target_user_id = uuid.UUID(raw["user_id"])
        except Exception:
            raise HTTPException(status_code=400, detail="invalid user_id")
    row, raw_key = await create_api_key(db, target_user_id)
    await db.commit()
    return {
        "id": str(row.id),
        "key": raw_key,  # shown once
        "prefix": row.prefix,
        "last4": row.last4,
        "created_at": row.created_at.isoformat(),
    }


@router.delete("/api/keys/{key_id}", status_code=200)
async def revoke_key(key_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user_via_session)):
    verify_csrf(request)
    res = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    row = res.scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="key not found")
    # only owner or admin can revoke
    if row.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="not allowed to revoke this key")
    ok = await revoke_api_key(db, key_id)
    await db.commit()
    return {"revoked": True}
