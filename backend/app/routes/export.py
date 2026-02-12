from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_optional_user
from app.db import get_session
from app.models.mini import Mini
from app.models.team import Team, TeamMember
from app.models.user import User

router = APIRouter(prefix="/export", tags=["export"])


def _check_visibility(mini: Mini, user: User | None) -> None:
    """Raise 404 if mini is private and user is not the owner."""
    if mini.visibility == "private":
        if user is None or user.id != mini.owner_id:
            raise HTTPException(status_code=404, detail="Mini not found")


def _generate_subagent_md(mini: Mini) -> str:
    """Generate a Claude Code agent definition in .md format."""
    display = mini.display_name or mini.username
    lines = [
        "---",
        f"name: {mini.username}-mini",
        "model: claude-sonnet-4-5-20250929",
        "tools:",
        "  - mcp: minis",
        "    tools: [chat_with_mini, get_mini_memory]",
        "---",
        "",
        f"You are an AI personality clone of {display} (@{mini.username}).",
        "",
    ]
    if mini.spirit_content:
        lines.append(mini.spirit_content)
        lines.append("")

    if mini.memory_content:
        lines.append("## Memory Bank")
        lines.append(mini.memory_content)
        lines.append("")

    return "\n".join(lines)


@router.get("/minis/{mini_id}/subagent", response_class=PlainTextResponse)
async def export_subagent(
    mini_id: int,
    format: str = "claude_code",
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Export a mini as a Claude Code agent definition (.md file)."""
    result = await session.execute(select(Mini).where(Mini.id == mini_id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    _check_visibility(mini, user)

    if mini.status != "ready":
        raise HTTPException(status_code=409, detail=f"Mini not ready (status: {mini.status})")

    content = _generate_subagent_md(mini)
    return PlainTextResponse(content, media_type="text/markdown")


@router.get("/minis/{mini_id}/soul-doc", response_class=PlainTextResponse)
async def export_soul_doc(
    mini_id: int,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Export a mini's raw spirit document (soul doc)."""
    result = await session.execute(select(Mini).where(Mini.id == mini_id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    _check_visibility(mini, user)

    if not mini.spirit_content:
        raise HTTPException(status_code=404, detail="No spirit content available")

    return PlainTextResponse(mini.spirit_content, media_type="text/markdown")


@router.get("/teams/{team_id}/agent-team")
async def export_team_agents(
    team_id: int,
    format: str = "claude_code",
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Export all minis in a team as Claude Code agent definitions.

    Returns JSON with agent .md files and a team config YAML.
    """
    result = await session.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Fetch member minis
    stmt = (
        select(Mini)
        .join(TeamMember, TeamMember.mini_id == Mini.id)
        .where(TeamMember.team_id == team_id)
    )
    result = await session.execute(stmt)
    minis = result.scalars().all()

    agents = []
    agent_names = []
    for mini in minis:
        if mini.status != "ready":
            continue
        md_content = _generate_subagent_md(mini)
        filename = f"{mini.username}-mini.md"
        agents.append({"filename": filename, "content": md_content})
        agent_names.append(f"{mini.username}-mini")

    # Generate team config YAML
    team_desc = team.description or f"Team of {len(agent_names)} minis"
    config_lines = [
        f"# Team: {team.name}",
        f"# {team_desc}",
        "",
        "agents:",
    ]
    for name in agent_names:
        config_lines.append(f"  - {name}")

    config = "\n".join(config_lines)

    return {"agents": agents, "config": config}
