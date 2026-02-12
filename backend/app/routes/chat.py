from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.agent import AgentTool, run_agent_streaming
from app.core.auth import get_optional_user
from app.core.encryption import decrypt_value
from app.core.rate_limit import check_rate_limit
from app.db import get_session
from app.models.mini import Mini
from app.models.schemas import ChatRequest
from app.models.user import User
from app.models.user_settings import UserSettings

router = APIRouter(prefix="/minis", tags=["chat"])


def _build_chat_tools(mini: Mini) -> list[AgentTool]:
    """Build the tools available to a mini during chat."""

    async def search_memories(query: str) -> str:
        """Search the mini's memory bank for facts about a topic."""
        if not mini.memory_content:
            return "No memories available."
        query_lower = query.lower()
        lines = mini.memory_content.split("\n")
        matches = []
        for i, line in enumerate(lines):
            if query_lower in line.lower():
                # Include surrounding context (2 lines before/after)
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                context = "\n".join(lines[start:end])
                matches.append(context)
        if not matches:
            return f"No memories found matching '{query}'."
        # Deduplicate overlapping contexts
        seen = set()
        unique = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return "\n\n---\n\n".join(unique[:10])

    async def search_evidence(query: str) -> str:
        """Search raw ingestion evidence for quotes and examples."""
        if not mini.evidence_cache:
            return "No evidence available."
        query_lower = query.lower()
        lines = mini.evidence_cache.split("\n")
        matches = []
        for i, line in enumerate(lines):
            if query_lower in line.lower():
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                context = "\n".join(lines[start:end])
                matches.append(context)
        if not matches:
            return f"No evidence found matching '{query}'."
        seen = set()
        unique = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return "\n\n---\n\n".join(unique[:10])

    async def think(reasoning: str) -> str:
        """Internal reasoning step -- work through a problem before responding."""
        return "OK"

    tools = [
        AgentTool(
            name="search_memories",
            description="Search your memory bank for facts, opinions, projects, or experiences related to a topic. Use this to recall specific details before answering.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query -- a keyword or topic to search for in memories",
                    },
                },
                "required": ["query"],
            },
            handler=search_memories,
        ),
        AgentTool(
            name="search_evidence",
            description="Search raw evidence (code reviews, commits, PRs, comments) for exact quotes and examples. Use this when you need to cite specific things you've said or done.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query -- a keyword or topic to search for in raw evidence",
                    },
                },
                "required": ["query"],
            },
            handler=search_evidence,
        ),
        AgentTool(
            name="think",
            description="Think through a problem step by step before responding. Use this for complex questions that require reasoning.",
            parameters={
                "type": "object",
                "properties": {
                    "reasoning": {
                        "type": "string",
                        "description": "Your step-by-step reasoning about the question",
                    },
                },
                "required": ["reasoning"],
            },
            handler=think,
        ),
    ]

    return tools


@router.post("/{mini_id}/chat")
async def chat_with_mini(
    mini_id: int,
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Send a message and get a streaming SSE response from the mini using agentic chat."""
    result = await session.execute(
        select(Mini).where(Mini.id == mini_id)
    )
    mini = result.scalar_one_or_none()

    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    # Visibility check: private minis are owner-only
    if mini.visibility == "private":
        if user is None or user.id != mini.owner_id:
            raise HTTPException(status_code=404, detail="Mini not found")

    if mini.status != "ready":
        raise HTTPException(status_code=409, detail=f"Mini is not ready (status: {mini.status})")
    if not mini.system_prompt:
        raise HTTPException(status_code=500, detail="Mini has no system prompt")

    # Rate limit check (only for authenticated users)
    if user is not None:
        await check_rate_limit(user.id, "chat_message", session)

    # Resolve model and API key from user settings
    resolved_model: str | None = None
    resolved_api_key: str | None = None
    if user is not None:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user.id)
        )
        user_settings = result.scalar_one_or_none()
        if user_settings:
            resolved_model = user_settings.preferred_model
            if user_settings.llm_api_key:
                try:
                    resolved_api_key = decrypt_value(user_settings.llm_api_key)
                except Exception:
                    resolved_api_key = None

    system_prompt = mini.system_prompt

    # Apply context-specific voice modulation if requested
    if body.context:
        from app.models.context import CommunicationContext
        from app.synthesis.spirit import build_contextual_system_prompt

        ctx_result = await session.execute(
            select(CommunicationContext).where(
                CommunicationContext.mini_id == mini_id,
                CommunicationContext.context_key == body.context,
            )
        )
        ctx = ctx_result.scalar_one_or_none()
        if ctx:
            system_prompt = build_contextual_system_prompt(
                mini.username,
                mini.spirit_content or "",
                mini.memory_content or "",
                ctx.voice_modulation,
            )

    tools = _build_chat_tools(mini)

    # Build conversation history for the agent
    history: list[dict] = []
    for msg in body.history:
        history.append({"role": msg.role, "content": msg.content})

    async def event_generator():
        async for event in run_agent_streaming(
            system_prompt=system_prompt,
            user_prompt=body.message,
            tools=tools,
            history=history,
            max_turns=15,
            model=resolved_model,
            api_key=resolved_api_key,
        ):
            yield {"event": event.type, "data": event.data}

    return EventSourceResponse(event_generator())
