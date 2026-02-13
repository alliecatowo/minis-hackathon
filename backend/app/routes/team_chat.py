import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.access import require_team_access
from app.core.agent import AgentEvent, run_agent_streaming
from app.core.auth import get_current_user
from app.core.rate_limit import check_rate_limit
from app.db import get_session
from app.models.mini import Mini
from app.models.team import Team, TeamMember
from app.models.user import User
from app.routes.chat import _build_chat_tools

router = APIRouter(prefix="/teams", tags=["team_chat"])


class TeamChatRequest(BaseModel):
    message: str
    context: str | None = None


async def _collect_mini_response(
    mini: Mini,
    message: str,
) -> list[AgentEvent]:
    """Run agent for a single mini and collect all events."""
    tools = _build_chat_tools(mini)
    events: list[AgentEvent] = []
    async for event in run_agent_streaming(
        system_prompt=mini.system_prompt,
        user_prompt=message,
        tools=tools,
        max_turns=10,
    ):
        events.append(event)
    return events


@router.post("/{team_id}/chat")
async def team_chat(
    team_id: str,
    body: TeamChatRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Send a message to all minis in a team and stream their responses via SSE."""
    await check_rate_limit(user.id, "team_chat", session)

    # Fetch team
    result = await session.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    await require_team_access(team, user, session)

    # Fetch member minis
    stmt = (
        select(Mini)
        .join(TeamMember, TeamMember.mini_id == Mini.id)
        .where(TeamMember.team_id == team_id)
    )
    result = await session.execute(stmt)
    minis = result.scalars().all()

    if not minis:
        raise HTTPException(status_code=400, detail="Team has no members")

    # Filter to ready minis with system prompts
    ready_minis = [m for m in minis if m.status == "ready" and m.system_prompt]
    if not ready_minis:
        raise HTTPException(status_code=409, detail="No team members are ready")

    # Build the message, optionally prepending context
    message = body.message
    if body.context:
        message = f"Context: {body.context}\n\n{message}"

    async def event_generator():
        # Run all minis in parallel
        tasks = [_collect_mini_response(mini, message) for mini in ready_minis]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Emit responses sequentially per mini
        for mini, result in zip(ready_minis, results):
            display = mini.display_name or mini.username
            yield {
                "event": "member_start",
                "data": json.dumps({
                    "mini_id": mini.id,
                    "username": mini.username,
                    "display_name": display,
                }),
            }

            if isinstance(result, Exception):
                yield {
                    "event": "member_chunk",
                    "data": json.dumps({
                        "mini_id": mini.id,
                        "chunk": f"Error: {result}",
                    }),
                }
            else:
                for event in result:
                    if event.type == "chunk":
                        yield {
                            "event": "member_chunk",
                            "data": json.dumps({
                                "mini_id": mini.id,
                                "chunk": event.data,
                            }),
                        }

            yield {
                "event": "member_done",
                "data": json.dumps({"mini_id": mini.id}),
            }

        yield {"event": "done", "data": "All members responded"}

    return EventSourceResponse(event_generator())
