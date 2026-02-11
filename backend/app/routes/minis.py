import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.auth import get_current_user, get_optional_user
from app.db import async_session, get_session
from app.models.mini import Mini
from app.models.schemas import CreateMiniRequest, MiniDetail, MiniSummary
from app.models.user import User
from app.plugins.registry import registry
from app.synthesis.pipeline import (
    cleanup_event_queue,
    get_event_queue,
    run_pipeline_with_events,
)

router = APIRouter(prefix="/minis", tags=["minis"])


@router.get("/sources")
async def list_sources():
    """List available ingestion sources."""
    source_names = registry.list_sources()
    source_info = {
        "github": {"name": "GitHub", "description": "Commits, PRs, and reviews"},
        "claude_code": {"name": "Claude Code", "description": "Conversation history"},
        "blog": {"name": "Blog / RSS", "description": "Blog posts and articles via RSS feed"},
        "hackernews": {"name": "Hacker News", "description": "Comments, posts, and tech opinions"},
        "stackoverflow": {"name": "Stack Overflow", "description": "Top answers and expertise"},
        "devblog": {"name": "Dev.to", "description": "Dev.to articles, tutorials, and discussions"},
    }
    return [
        {
            "id": s,
            "name": source_info.get(s, {}).get("name", s),
            "description": source_info.get(s, {}).get("description", ""),
            "available": True,
        }
        for s in source_names
    ]


@router.post("", status_code=202)
async def create_mini(
    body: CreateMiniRequest,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Create a new mini. Kicks off pipeline in background with selected sources."""
    username = body.username.strip().lower()
    sources = body.sources
    owner_id = user.id if user else None

    # Check if already exists
    result = await session.execute(
        select(Mini).where(Mini.username == username)
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Re-run pipeline (allows regeneration and recovery from stuck state)
        existing.status = "processing"
        if owner_id and not existing.owner_id:
            existing.owner_id = owner_id
        await session.commit()
        mini = existing
    else:
        # Create new
        mini = Mini(username=username, status="processing", owner_id=owner_id)
        session.add(mini)
        await session.commit()
        await session.refresh(mini)

    # Kick off pipeline in background
    asyncio.create_task(
        run_pipeline_with_events(username, async_session, sources=sources, owner_id=owner_id)
    )

    return MiniSummary.model_validate(mini)


@router.get("")
async def list_minis(
    session: AsyncSession = Depends(get_session),
):
    """List all minis."""
    result = await session.execute(
        select(Mini).order_by(Mini.created_at.desc())
    )
    minis = result.scalars().all()
    return [MiniSummary.model_validate(m) for m in minis]


@router.get("/{username}")
async def get_mini(
    username: str,
    session: AsyncSession = Depends(get_session),
):
    """Get full mini details."""
    result = await session.execute(
        select(Mini).where(Mini.username == username.lower())
    )
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    return MiniDetail.model_validate(mini)


@router.delete("/{username}", status_code=204)
async def delete_mini(
    username: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Delete a mini. Owner only."""
    result = await session.execute(
        select(Mini).where(Mini.username == username.lower())
    )
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    if mini.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not the owner of this mini")
    await session.delete(mini)
    await session.commit()


@router.get("/{username}/status")
async def mini_status_stream(username: str):
    """SSE stream of pipeline progress events."""
    username = username.lower()
    queue = get_event_queue(username)

    async def event_generator():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=300)
                if event is None:
                    # Pipeline completed
                    yield {"event": "done", "data": "Pipeline completed"}
                    break
                yield {
                    "event": "progress",
                    "data": event.model_dump_json(),
                }
        except asyncio.TimeoutError:
            yield {"event": "timeout", "data": "Pipeline timed out"}
        finally:
            cleanup_event_queue(username)

    return EventSourceResponse(event_generator())
