"""Users + API keys routes (/api/users, /api/keys, /api/auth)."""

from __future__ import annotations

import uuid

from audit.admin_events import key_ref, login_failed_event_allowed, record_admin_event, sanitize_login_email
from auth import login_throttle
from auth.keys import create_api_key, revoke_api_key
from auth.rbac import (
    get_current_user_via_session,
    hash_password,
    require_admin,
    verify_csrf,
    verify_password,
)
from auth.session import clear_session_cookie, create_session_cookie, set_session_cookie, verify_session_cookie
from config import get_settings
from db.models import ApiKey, User
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["users"])


class LoginBody(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)
    role: str = Field(pattern=r"^(admin|member)$")


class KeyCreate(BaseModel):
    expires_at: str | None = None  # ISO8601


@router.post("/api/auth/login")
async def login(body: LoginBody, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    # Hardening (ADR-044): lockout per username AND per client IP. The counter is
    # in-memory => per replica (documented residual). The lockout check runs
    # BEFORE any credential work; a locked attempt never reaches password verify
    # and returns the generic 429 text (no user-existence leak either way).
    client_ip = request.client.host if request.client else "unknown"
    if login_throttle.is_locked("user", email) or login_throttle.is_locked("ip", client_ip):
        raise HTTPException(status_code=429, detail="too many attempts, retry later")
    res = await db.execute(select(User).where(User.email == email))
    user = res.scalars().first()
    reason = ""
    if not user or not user.is_active:
        reason = "invalid_credentials" if not user else "inactive"
    elif not await verify_password(user.password_hash, body.password):
        reason = "invalid_credentials"
    if reason:
        # Hardening (ADR-044): count the failure for both keys; when a cap is
        # crossed, write ONE audit row per lockout transition.
        just_locked_user = login_throttle.record_failure("user", email)
        just_locked_ip = login_throttle.record_failure("ip", client_ip)
        # login.failed trail (ADR-034): attempted email + time + reason only, NEVER
        # the password. One source (attempted email) can write at most
        # LOGIN_FAILED_EVENT_LIMIT rows per window (the same in-memory rate-limit
        # pattern as /mcp and check-now), so bad-login floods cannot flood the
        # table. The write commits here because this event IS the completed action;
        # the 401 below rolls the request session back otherwise.
        # target_ref is sanitized: only valid email format is stored, otherwise
        # "invalid_format" (prevents XSS from HTML in the email field).
        if just_locked_user or just_locked_ip:
            record_admin_event(
                db,
                actor_user_id=None,
                action="login.lockout",
                target_type="login",
                target_ref=sanitize_login_email(email),
                outcome="failure",
                details={"reason": "lockout", "client_ip": client_ip},
            )
            await db.commit()
        if login_failed_event_allowed(email):
            record_admin_event(
                db,
                actor_user_id=None,
                action="login.failed",
                target_type="login",
                target_ref=sanitize_login_email(email),
                outcome="failure",
                details={"reason": reason},
            )
            await db.commit()
        raise HTTPException(status_code=401, detail="invalid credentials")
    login_throttle.record_success("user", email)
    login_throttle.record_success("ip", client_ip)
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
    # user.invite trail: email + role only, the password never leaves the request
    record_admin_event(
        db,
        actor_user_id=user.id,
        action="user.invite",
        target_type="user",
        target_ref=u.email,
        details={"role": body.role, "user_id": str(u.id)},
    )
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
    record_admin_event(db, actor_user_id=admin.id, action="user.delete", target_type="user", target_ref=u.email)
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
                "rate_limit_per_minute": r.rate_limit_per_minute,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


class KeyLimitUpdate(BaseModel):
    """Admin per-key rate limit override (ADR-057). null clears back to the
    gateway default; an int must be 1..10000 (a limit of 0 would brick a key
    with one toggle)."""
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10000)


@router.patch("/api/keys/{key_id}", status_code=200)
async def update_key_limit(
    key_id: uuid.UUID,
    body: KeyLimitUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Admin-only per-key rate limit override. The override is the ONLY mutable
    key field: revocation stays the DELETE endpoint, and nothing here can touch
    credential material. Admin event records the new limit (not a secret)."""
    verify_csrf(request)
    res = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    row = res.scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="key not found")
    row.rate_limit_per_minute = body.rate_limit_per_minute
    record_admin_event(
        db,
        actor_user_id=user.id,
        action="key.update",
        target_type="key",
        target_ref=key_ref(row.prefix, row.last4),
        details={
            "owner_user_id": str(row.user_id),
            "key_id": str(row.id),
            "rate_limit_per_minute": body.rate_limit_per_minute,
        },
    )
    await db.commit()
    return {
        "id": str(row.id),
        "prefix": row.prefix,
        "last4": row.last4,
        "rate_limit_per_minute": row.rate_limit_per_minute,
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
            # from None: the ValueError payload says nothing the client may see
            raise HTTPException(status_code=400, detail="invalid user_id") from None
    row, raw_key = await create_api_key(db, target_user_id)
    # key.create trail: prefix + last4 and the owner id ONLY. The raw key above is
    # shown once in the response and must never appear in the trail.
    record_admin_event(
        db,
        actor_user_id=user.id,
        action="key.create",
        target_type="key",
        target_ref=key_ref(row.prefix, row.last4),
        details={"owner_user_id": str(target_user_id), "key_id": str(row.id)},
    )
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
    # revoke_api_key() returns False only for an unknown id, already 404'd above,
    # so this stays idempotent and the result is not a new response field.
    record_admin_event(
        db,
        actor_user_id=user.id,
        action="key.revoke",
        target_type="key",
        target_ref=key_ref(row.prefix, row.last4),
        details={"owner_user_id": str(row.user_id), "key_id": str(row.id)},
    )
    await revoke_api_key(db, key_id)
    await db.commit()
    return {"revoked": True}
