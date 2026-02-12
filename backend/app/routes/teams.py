import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_team_access
from app.core.auth import get_current_user
from app.db import get_session
from app.models.mini import Mini
from app.models.team import Team, TeamMember
from app.models.user import User

# -- Request schemas --


class TeamCreateRequest(BaseModel):
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)


class TeamUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class AddMemberRequest(BaseModel):
    mini_id: str
    role: str = Field(default="member", max_length=20)


# -- Response schemas --


class TeamSummaryResponse(BaseModel):
    id: str
    name: str
    description: str | None
    member_count: int
    owner_username: str
    created_at: datetime.datetime


class TeamMemberResponse(BaseModel):
    mini_id: str
    username: str
    role: str
    display_name: str | None
    avatar_url: str | None
    added_at: datetime.datetime


class TeamDetailResponse(BaseModel):
    id: str
    name: str
    description: str | None
    owner_username: str
    members: list[TeamMemberResponse]
    created_at: datetime.datetime


router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("", response_model=TeamDetailResponse, status_code=201)
async def create_team(
    body: TeamCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a new team."""
    team = Team(name=body.name, description=body.description, owner_id=user.id)
    session.add(team)
    await session.commit()
    await session.refresh(team)

    return TeamDetailResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        owner_username=user.github_username,
        members=[],
        created_at=team.created_at,
    )


@router.get("", response_model=list[TeamSummaryResponse])
async def list_teams(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List teams owned by the current user."""
    stmt = (
        select(
            Team.id,
            Team.name,
            Team.description,
            Team.created_at,
            User.github_username.label("owner_username"),
            func.count(TeamMember.id).label("member_count"),
        )
        .join(User, Team.owner_id == User.id)
        .outerjoin(TeamMember, Team.id == TeamMember.team_id)
        .where(Team.owner_id == user.id)
        .group_by(Team.id, User.github_username)
        .order_by(Team.created_at.desc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    return [
        TeamSummaryResponse(
            id=row.id,
            name=row.name,
            description=row.description,
            member_count=row.member_count,
            owner_username=row.owner_username,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/{team_id}", response_model=TeamDetailResponse)
async def get_team(
    team_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get team detail with members (owner or member only)."""
    # Fetch team with owner username
    stmt = (
        select(Team, User.github_username.label("owner_username"))
        .join(User, Team.owner_id == User.id)
        .where(Team.id == team_id)
    )
    result = await session.execute(stmt)
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Team not found")

    team = row[0]
    owner_username = row[1]

    await require_team_access(team, user, session)

    # Fetch members with mini details
    members_stmt = (
        select(
            TeamMember.mini_id,
            TeamMember.role,
            TeamMember.added_at,
            Mini.username,
            Mini.display_name,
            Mini.avatar_url,
        )
        .outerjoin(Mini, TeamMember.mini_id == Mini.id)
        .where(TeamMember.team_id == team_id)
        .order_by(TeamMember.added_at)
    )
    members_result = await session.execute(members_stmt)
    members = [
        TeamMemberResponse(
            mini_id=m.mini_id,
            username=m.username,
            role=m.role,
            display_name=m.display_name,
            avatar_url=m.avatar_url,
            added_at=m.added_at,
        )
        for m in members_result.all()
    ]

    return TeamDetailResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        owner_username=owner_username,
        members=members,
        created_at=team.created_at,
    )


@router.put("/{team_id}", response_model=TeamDetailResponse)
async def update_team(
    team_id: str,
    body: TeamUpdateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Update a team (owner only)."""
    result = await session.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not the team owner")

    if body.name is not None:
        team.name = body.name
    if body.description is not None:
        team.description = body.description

    await session.commit()
    await session.refresh(team)

    # Re-fetch full detail
    return await get_team(team_id, user, session)


@router.delete("/{team_id}", status_code=204)
async def delete_team(
    team_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete a team (owner only)."""
    result = await session.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not the team owner")

    await session.execute(
        delete(TeamMember).where(TeamMember.team_id == team_id)
    )
    await session.delete(team)
    await session.commit()


@router.post("/{team_id}/members", response_model=TeamMemberResponse, status_code=201)
async def add_member(
    team_id: str,
    body: AddMemberRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Add a mini to a team (owner only)."""
    result = await session.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not the team owner")

    # Check mini exists
    mini_result = await session.execute(
        select(Mini).where(Mini.id == body.mini_id)
    )
    mini = mini_result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    # Check not already a member
    existing = await session.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.mini_id == body.mini_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already a team member")

    member = TeamMember(
        team_id=team_id,
        mini_id=body.mini_id,
        role=body.role,
    )
    session.add(member)
    await session.commit()
    await session.refresh(member)

    return TeamMemberResponse(
        mini_id=member.mini_id,
        username=mini.username,
        role=member.role,
        display_name=mini.display_name,
        avatar_url=mini.avatar_url,
        added_at=member.added_at,
    )


@router.delete("/{team_id}/members/{mini_id}", status_code=204)
async def remove_member(
    team_id: str,
    mini_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Remove a mini from a team (owner only)."""
    result = await session.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not the team owner")

    member_result = await session.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.mini_id == mini_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    await session.delete(member)
    await session.commit()
