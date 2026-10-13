"""Two pure-Python time tools for the demo Time MCP server."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.types import ToolAnnotations
from pydantic import BeforeValidator, Field

logger = logging.getLogger("demo-time.tools")

TZ_NAME = Annotated[str, Field(min_length=1, max_length=64, description="IANA timezone name, e.g. Europe/Berlin")]


def blank_to_none(value):
    """Treat a blank optional string as "not provided".

    The MCP Inspector renders a text input for every string parameter and submits ""
    for empty ones, so an unfilled timezone must behave like an omitted one
    (default UTC) instead of failing the min_length=1 schema check.
    """

    if isinstance(value, str) and not value.strip():
        return None
    return value


def _serialise(payload) -> str:
    return json.dumps(payload, default=str, separators=(",", ":"))


def _resolve(tz_name: str) -> ZoneInfo:
    """Map a timezone name to ZoneInfo; leave a bad name for the tool to report."""

    if not tz_name:
        raise ValueError("timezone must be a non-empty IANA name")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Unknown timezone '{tz_name}' (use an IANA name like Europe/Berlin)"
        ) from exc
    except ValueError as exc:  # malformed string, not a tz data problem
        raise ValueError(f"Invalid timezone string '{tz_name}'") from exc


def register_tools(mcp) -> None:
    @mcp.tool(
        name="get_current_time",
        title="Get current time",
        description="Current UTC time, plus the local time in an optional IANA timezone.",
        annotations=ToolAnnotations(
            title="Get current time", readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    async def get_current_time(
        timezone_name: Annotated[TZ_NAME | None, BeforeValidator(blank_to_none)] = None,
    ) -> str:
        tz_name = timezone_name or "UTC"
        tz = _resolve(tz_name)
        now_local = datetime.now(tz)
        return _serialise(
            {
                "now_utc": datetime.now(UTC).isoformat(),
                "timezone": tz_name,
                "now_local": now_local.isoformat(),
                "utc_offset_minutes": int(now_local.utcoffset().total_seconds() // 60),
            }
        )

    @mcp.tool(
        name="convert_time",
        title="Convert time",
        description="Convert a wall-clock time between two IANA timezones.",
        annotations=ToolAnnotations(
            title="Convert time", readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    async def convert_time(
        time: Annotated[str, Field(description="ISO-8601 datetime, e.g. 2026-10-10T14:30:00")],
        from_tz: TZ_NAME,
        to_tz: TZ_NAME,
    ) -> str:
        try:
            naive = datetime.fromisoformat(time)
        except ValueError as exc:
            raise ValueError(f"Invalid datetime '{time}' (expected ISO-8601)") from exc

        source_tz = _resolve(from_tz)
        target_tz = _resolve(to_tz)

        aware = naive.replace(tzinfo=source_tz)
        converted = aware.astimezone(target_tz)
        return _serialise(
            {
                "input": time,
                "from_timezone": from_tz,
                "to_timezone": to_tz,
                "from_local": aware.isoformat(),
                "to_local": converted.isoformat(),
                "offset_difference_minutes": int(
                    (
                        converted.utcoffset().total_seconds()
                        - aware.utcoffset().total_seconds()
                    )
                    // 60
                ),
            }
        )

    logger.info("registered 2 demo-time tools")
