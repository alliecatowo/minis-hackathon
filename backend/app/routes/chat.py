from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.llm import llm_stream
from app.db import get_session
from app.models.mini import Mini
from app.models.schemas import ChatRequest

router = APIRouter(prefix="/minis", tags=["chat"])


@router.post("/{username}/chat")
async def chat_with_mini(
    username: str,
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
):
    """Send a message and get a streaming SSE response from the mini."""
    result = await session.execute(
        select(Mini).where(Mini.username == username.lower())
    )
    mini = result.scalar_one_or_none()

    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    if mini.status != "ready":
        raise HTTPException(status_code=409, detail=f"Mini is not ready (status: {mini.status})")
    if not mini.system_prompt:
        raise HTTPException(status_code=500, detail="Mini has no system prompt")

    # Build messages for LLM
    messages: list[dict] = [{"role": "system", "content": mini.system_prompt}]

    # Add conversation history
    for msg in body.history:
        messages.append({"role": msg.role, "content": msg.content})

    # Add current user message
    messages.append({"role": "user", "content": body.message})

    async def event_generator():
        async for chunk in llm_stream(messages):
            yield {"event": "chunk", "data": chunk}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator())
