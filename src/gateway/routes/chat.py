"""Chat SSE endpoint: POST /api/chat/completions (F3: + image uploads as vision)."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from uuid import UUID

from auth.rbac import get_current_user_via_session
from config import get_settings
from db.session import get_db
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/chat", tags=["chat"])

# F3: at most two images per user turn keeps the vision request well inside the
# provider's inline-data budget (5 MB cap each, re-encoded).
MAX_IMAGES_PER_MESSAGE = 2


class ChatBody(BaseModel):
    messages: list[dict] = Field(default_factory=list)


def model_supports_vision(model: str) -> bool:
    """Best-effort vision capability check for the configured model chain.

    Known text-only families are denied; known multimodal families are allowed;
    an UNKNOWN name is attempted (providers reject non-vision input with a 400
    that the chat error path surfaces). The live chain is gemini-* (vision).
    """

    m = (model or "").lower()
    text_only = ("gpt-3.5", "o1-mini", "o1-preview", "text-embedding")
    vision_hints = (
        "gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-5", "o3", "o4", "gemini", "claude-3",
        "claude-sonnet", "claude-opus", "claude-haiku", "vision", "qwen", "llava",
        "pixtral", "glm-4v",
    )
    if any(x in m for x in text_only):
        return False
    if any(x in m for x in vision_hints):
        return True
    return True  # unknown family: attempt the call, the provider error is mapped


async def expand_messages(db, user, raw_messages: list[dict]) -> tuple[list[dict] | None, JSONResponse | None]:
    """Validate client messages and expand upload references into vision parts.

    History turns arrive as plain strings (the dashboard stores only an
    "[image]" placeholder, never bytes). The CURRENT turn may carry content as a
    part list: [{"type":"text",...},{"type":"image_upload","upload_id":...}].
    Each upload is resolved server-side, owner-checked and expiry-checked, and
    becomes an image_url part whose data URL exists only inside this LLM call.
    """

    from db.models import ChatUpload
    from sqlalchemy import select

    msgs: list[dict] = []
    image_count = 0
    for m in raw_messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant", "system"):
            continue
        if isinstance(content, str):
            msgs.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue
        # Part-list content: only the user role may attach uploads.
        if role != "user":
            return None, JSONResponse(
                {"detail": "only user messages may carry image parts"}, status_code=400
            )
        parts: list[dict] = []
        for part in content:
            if not isinstance(part, dict):
                return None, JSONResponse({"detail": "invalid message part"}, status_code=400)
            ptype = part.get("type")
            if ptype == "text":
                if isinstance(part.get("text"), str) and part.get("text"):
                    parts.append({"type": "text", "text": part["text"]})
            elif ptype == "image_upload":
                upload_id = part.get("upload_id")
                if not isinstance(upload_id, str) or not upload_id:
                    return None, JSONResponse({"detail": "image_upload requires upload_id"}, status_code=400)
                try:
                    uid = UUID(upload_id)
                except ValueError:
                    return None, JSONResponse({"detail": "unknown upload"}, status_code=404)
                res = await db.execute(select(ChatUpload).where(ChatUpload.id == uid))
                row = res.scalars().first()
                # Owner-bound: a user can only use their own upload ids.
                if row is None or row.user_id != user.id:
                    return None, JSONResponse(
                        {"detail": "unknown upload (uploads are private to the user who attached them)"},
                        status_code=404,
                    )
                # sqlite returns naive datetimes, Postgres aware ones — normalize
                expires = row.expires_at.replace(tzinfo=UTC) if row.expires_at and row.expires_at.tzinfo is None else row.expires_at
                if expires and expires <= datetime.now(UTC):
                    return None, JSONResponse(
                        {"detail": "that upload has expired (uploads live 15 minutes) — attach the image again"},
                        status_code=410,
                    )
                image_count += 1
                if image_count > MAX_IMAGES_PER_MESSAGE:
                    return None, JSONResponse(
                        {"detail": f"at most {MAX_IMAGES_PER_MESSAGE} images per message"}, status_code=400
                    )
                b64 = base64.b64encode(row.bytes).decode()
                parts.append({"type": "image_url", "image_url": {"url": f"data:{row.mime};base64,{b64}"}})
                # The model must be able to REFERENCE the upload (the helper takes
                # upload_id) without ever seeing base64: a marker text part names
                # the id, which is not secret (it belongs to this user anyway).
                parts.append({"type": "text", "text": f"[image attached, upload_id={upload_id}]"})
            else:
                return None, JSONResponse({"detail": "unsupported message part"}, status_code=400)
        if parts:
            msgs.append({"role": "user", "content": parts})
    if not msgs:
        return None, JSONResponse({"detail": "messages required"}, status_code=400)
    return msgs, None


@router.post("/completions")
async def chat_completions(
    body: ChatBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    msgs, error = await expand_messages(db, user, body.messages)
    if error is not None:
        return error

    if not msgs:
        return JSONResponse({"detail": "messages required"}, status_code=400)

    settings = get_settings()
    if not settings.openai_api_key:
        # Return non-SSE JSON so dashboard can show message without SSE parsing
        return JSONResponse(
            {"content": "Chat is not configured: the gateway-llm Secret has an empty OPENAI_API_KEY. Put a real key in it (or set gateway.llm.existingSecret) and upgrade.", "tool_calls": []}
        )

    # F3: when the turn carries an image, the ACTIVE model chain must support
    # vision input; a text-only chain gets a clear message instead of a raw
    # provider 400.
    chain = settings.model_chain()
    has_image = any(isinstance(m.get("content"), list) for m in msgs)
    if has_image and not any(model_supports_vision(m) for m in chain):
        return JSONResponse(
            {
                "content": "The configured chat model does not support image input. Remove the image or configure a vision model (gateway.llm.model in the Helm values).",
                "tool_calls": [],
            },
            status_code=400,
        )

    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    from chat.agent import chat_loop

    async def sse_gen():
        async for evt in chat_loop(db, user, msgs, request_id):
            data = json.dumps(evt, default=str)
            yield f"data: {data}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse_gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
