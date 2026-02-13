from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mini import Mini
from app.models.team import Team, TeamMember
from app.models.user import User


def require_mini_access(mini: Mini, user: User | None) -> None:
    """Check that user can read this mini. Public minis are open; private/team require ownership."""
    if mini.visibility == "public":
        return
    if user is None:
        raise HTTPException(status_code=404, detail="Mini not found")
    if mini.owner_id == user.id:
        return
    raise HTTPException(status_code=404, detail="Mini not found")


def require_mini_owner(mini: Mini, user: User | None) -> None:
    """Check that user owns this mini (for write operations)."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if mini.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not the owner of this mini")


async def require_team_access(
    team: Team, user: User | None, session: AsyncSession
) -> None:
    """Check that user can access this team (owner or has a mini in it)."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if team.owner_id == user.id:
        return
    # Check if user owns any mini that is a member of this team
    result = await session.execute(
        select(TeamMember)
        .join(Mini, TeamMember.mini_id == Mini.id)
        .where(TeamMember.team_id == team.id, Mini.owner_id == user.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a team member")


def require_team_owner(team: Team, user: User | None) -> None:
    """Check that user owns this team."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if team.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not the team owner")
