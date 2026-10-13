"""Probes for gateway itself."""

from __future__ import annotations

from config import get_settings
from db.session import get_db
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "service": get_settings().service_name, "version": get_settings().service_version}


@router.get("/readyz")
async def readyz(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        return {"status": "unready", "reason": str(exc)[:200]}
