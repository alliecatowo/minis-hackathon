from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.agent import AgentTool, run_agent_streaming
from app.db import get_session
from app.models.mini import Mini
from app.models.schemas import ChatRequest

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
        """Internal reasoning step — work through a problem before responding."""
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
                        "description": "Search query — a keyword or topic to search for in memories",
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
                        "description": "Search query — a keyword or topic to search for in raw evidence",
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


@router.post("/{username}/chat")
async def chat_with_mini(
    username: str,
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
):
    """Send a message and get a streaming SSE response from the mini using agentic chat."""
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

    tools = _build_chat_tools(mini)

    # Build conversation history for the agent
    history: list[dict] = []
    for msg in body.history:
        history.append({"role": msg.role, "content": msg.content})

    async def event_generator():
        async for event in run_agent_streaming(
            system_prompt=mini.system_prompt,
            user_prompt=body.message,
            tools=tools,
            history=history,
            max_turns=15,
        ):
            yield {"event": event.type, "data": event.data}

    return EventSourceResponse(event_generator())
