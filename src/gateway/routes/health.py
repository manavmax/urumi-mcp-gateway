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
    except Exception as exc:
        return {"status": "unready", "reason": str(exc)[:200]}
    # RC hardening: after a rolled-back or silently-uncommitted migration the
    # gateway must not report ready (companion to ADR-061). None = the startup
    # check has not run yet (transient migration connection failure keeps the
    # existing retry behaviour); False = ran and MISMATCHED - never ready.
    from db import schema_check

    if schema_check.schema_verified is False:
        return {
            "status": "unready",
            "reason": "database schema version does not match the code's alembic head",
        }
    return {"status": "ready"}
