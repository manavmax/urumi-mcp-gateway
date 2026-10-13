"""Chat SSE endpoint: POST /api/chat/completions."""

from __future__ import annotations

import json
import uuid

from auth.rbac import get_current_user_via_session
from config import get_settings
from db.session import get_db
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatBody(BaseModel):
    messages: list[dict] = Field(default_factory=list)


@router.post("/completions")
async def chat_completions(
    body: ChatBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_via_session),
):
    # Validate messages shape
    msgs = []
    for m in body.messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant", "system") and isinstance(content, str):
            msgs.append({"role": role, "content": content})

    if not msgs:
        return JSONResponse({"detail": "messages required"}, status_code=400)

    settings = get_settings()
    if not settings.openai_api_key:
        # Return non-SSE JSON so dashboard can show message without SSE parsing
        return JSONResponse(
            {"content": "Chat is not configured: the gateway-llm Secret has an empty OPENAI_API_KEY. Put a real key in it (or set gateway.llm.existingSecret) and upgrade.", "tool_calls": []}
        )

    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    from chat.agent import chat_loop

    async def sse_gen():
        async for evt in chat_loop(db, user, msgs, request_id):
            data = json.dumps(evt, default=str)
            yield f"data: {data}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse_gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
