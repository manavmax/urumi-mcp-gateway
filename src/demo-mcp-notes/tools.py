"""In-memory notes for the demo Notes MCP server (no database, no persistence).

Tool calls return stored notes as text; the store is process-local, which is exactly
what this demo needs - it never leaves the cluster and loses data on restart.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from mcp.types import ToolAnnotations
from pydantic import Field
from typing import Annotated

logger = logging.getLogger("demo-notes.tools")

TITLE = Annotated[str, Field(min_length=1, max_length=200)]
BODY = Annotated[str, Field(min_length=1, max_length=20_000)]
QUERY = Annotated[str, Field(min_length=1, max_length=200)]


class NoteStore:
    """Thread-safe in-memory note store (single process, no persistence)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._notes: list[dict] = []
        self._next_id = 1

    def create(self, title: str, body: str) -> dict:
        with self._lock:
            note = {
                "id": self._next_id,
                "title": title,
                "body": body,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._next_id += 1
            self._notes.append(note)
            return dict(note)

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(n) for n in self._notes]

    def search(self, query: str) -> list[dict]:
        needle = query.strip().lower()
        with self._lock:
            hits = [
                dict(n)
                for n in self._notes
                if needle in n["title"].lower() or needle in n["body"].lower()
            ]
        return hits


def _serialise(payload) -> str:
    return json.dumps(payload, default=str, separators=(",", ":"))


def register_tools(mcp, store: NoteStore) -> None:
    @mcp.tool(
        name="create_note",
        title="Create note",
        description="Create a note with a title and a body; returns the new note id.",
        annotations=ToolAnnotations(
            title="Create note", readOnlyHint=False, destructiveHint=False, idempotentHint=False
        ),
    )
    async def create_note(title: TITLE, body: BODY) -> str:
        note = store.create(title=title, body=body)
        logger.info("created note id=%s title=%r", note["id"], note["title"])
        return _serialise({"created": True, "note": note})

    @mcp.tool(
        name="list_notes",
        title="List notes",
        description="List all notes (newest last) with id, title and created_at.",
        annotations=ToolAnnotations(
            title="List notes", readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    async def list_notes() -> str:
        notes = store.list()
        return _serialise(
            {
                "notes": [
                    {"id": n["id"], "title": n["title"], "created_at": n["created_at"]}
                    for n in notes
                ],
                "count": len(notes),
            }
        )

    @mcp.tool(
        name="search_notes",
        title="Search notes",
        description="Case-insensitive search across note titles and bodies.",
        annotations=ToolAnnotations(
            title="Search notes", readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    async def search_notes(query: QUERY) -> str:
        hits = store.search(query)
        return _serialise({"query": query, "matches": hits, "count": len(hits)})

    logger.info("registered 3 demo-notes tools")
