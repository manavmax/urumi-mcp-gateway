"""POST /api/chat/uploads — chat image upload endpoint (F3, ADR-035).

Session-authenticated, CSRF-protected, per-user rate limited (10 uploads per
minute). Bytes are validated by the shared helper (magic bytes only: png/jpeg/
webp; 5 MB cap, 4096 px per side, decompression-bomb guard; Pillow re-encode
strips EXIF/GPS and polyglot payloads) and stored in chat_uploads for 15
minutes, bound to the uploading user. The response never echoes the bytes; the
model never sees base64 (the gateway expands the row into a vision part of the
LLM call server-side).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from auth.rbac import get_current_user_via_session, verify_csrf
from config import get_settings
from db.models import ChatUpload
from db.session import get_db
from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from uploads.validate import ImageValidationError, http_status_of, validate_image

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Per-user upload limiter: 10 uploads per rolling minute (in-memory, the same
# per-process trade-off as the per-key MCP limiter in routes/mcp.py).
UPLOAD_RATE_LIMIT_PER_MINUTE = 10
_rate_buckets: dict[str, list[float]] = {}


def _check_upload_rate_limit(user_id: str) -> bool:
    now = time.time()
    bucket = [t for t in _rate_buckets.get(user_id, []) if now - t < 60.0]
    if len(bucket) >= UPLOAD_RATE_LIMIT_PER_MINUTE:
        _rate_buckets[user_id] = bucket
        return False
    bucket.append(now)
    _rate_buckets[user_id] = bucket
    return True


async def purge_expired_uploads(db: AsyncSession) -> int:
    """Delete every expired upload row. Returns the number purged."""

    from db.models import ChatUpload
    from sqlalchemy import delete as _delete

    res = await db.execute(_delete(ChatUpload).where(ChatUpload.expires_at <= datetime.now(UTC)))
    await db.commit()
    return int(res.rowcount or 0)


@router.post("/uploads")
async def upload_chat_image(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    verify_csrf(request)
    if not _check_upload_rate_limit(str(user.id)):
        return JSONResponse(
            {"detail": "upload rate limit exceeded (10 per minute) — try again in a minute"},
            status_code=429,
        )
    settings = get_settings()

    # Refuse over-cap payloads BEFORE reading them into memory. The declared
    # size is advisory (the magic-byte validator decides from the bytes).
    cap = settings.image_upload_max_bytes + 1_048_576
    size = getattr(file, "size", None)
    if size is not None and size > cap:
        return JSONResponse(
            {"detail": "image exceeds the 5 MB cap", "code": "IMAGE_TOO_LARGE"}, status_code=413
        )
    data = await file.read()
    if len(data) > cap:
        return JSONResponse(
            {"detail": "image exceeds the 5 MB cap", "code": "IMAGE_TOO_LARGE"}, status_code=413
        )

    try:
        reencoded, mime = validate_image(data, max_bytes=settings.image_upload_max_bytes)
    except ImageValidationError as exc:
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=http_status_of(exc))

    # Opportunistic purge: this user's expired rows go with every upload, and a
    # background loop (main.py) sweeps everyone's on a minute cadence.
    now = datetime.now(UTC)
    await db.execute(delete(ChatUpload).where(ChatUpload.expires_at <= now))
    row = ChatUpload(
        user_id=user.id,
        bytes=reencoded,
        mime=mime,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.chat_upload_ttl_seconds),
    )
    db.add(row)
    await db.commit()
    return {
        "upload_id": str(row.id),
        "mime": mime,
        "size": len(reencoded),
        "expires_at": row.expires_at.isoformat(),
    }
