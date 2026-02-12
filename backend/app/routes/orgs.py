import datetime
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db import get_session
from app.models.mini import Mini
from app.models.org import OrgInvitation, OrgMember, Organization
from app.models.team import Team, TeamMember
from app.models.user import User

# -- Request schemas --


class OrgCreateRequest(BaseModel):
    name: str
    display_name: str
    description: str | None = None
    avatar_url: str | None = None


class OrgUpdateRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    avatar_url: str | None = None


class InviteCreateRequest(BaseModel):
    max_uses: int = 0
    expires_in_hours: int | None = None


class OrgTeamCreateRequest(BaseModel):
    name: str
    description: str | None = None


# -- Response schemas --


class OrgSummaryResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str | None
    avatar_url: str | None
    member_count: int
    role: str
    created_at: datetime.datetime


class OrgMemberResponse(BaseModel):
    id: int
    user_id: int
    username: str
    display_name: str | None
    avatar_url: str | None
    role: str
    joined_at: datetime.datetime


class OrgMemberWithMinisResponse(BaseModel):
    id: int
    user_id: int
    username: str
    display_name: str | None
    avatar_url: str | None
    role: str
    joined_at: datetime.datetime
    minis: list[dict]


class OrgDetailResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str | None
    avatar_url: str | None
    owner_id: int
    members: list[OrgMemberResponse]
    created_at: datetime.datetime


class InviteResponse(BaseModel):
    invite_code: str
    max_uses: int
    uses: int
    expires_at: datetime.datetime | None
    created_at: datetime.datetime


class OrgTeamSummaryResponse(BaseModel):
    id: int
    name: str
    description: str | None
    member_count: int
    owner_username: str
    created_at: datetime.datetime


router = APIRouter(prefix="/orgs", tags=["orgs"])


# -- Helpers --


async def _get_membership(
    session: AsyncSession, org_id: int, user_id: int
) -> OrgMember | None:
    result = await session.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def _require_membership(
    session: AsyncSession, org_id: int, user_id: int
) -> OrgMember:
    member = await _get_membership(session, org_id, user_id)
    if not member:
        raise HTTPException(status_code=403, detail="Not an org member")
    return member


async def _require_admin(
    session: AsyncSession, org_id: int, user_id: int
) -> OrgMember:
    member = await _require_membership(session, org_id, user_id)
    if member.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return member


async def _require_owner(
    session: AsyncSession, org_id: int, user_id: int
) -> OrgMember:
    member = await _require_membership(session, org_id, user_id)
    if member.role != "owner":
        raise HTTPException(status_code=403, detail="Owner role required")
    return member


async def _get_org_or_404(session: AsyncSession, org_id: int) -> Organization:
    result = await session.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


async def _get_org_members(
    session: AsyncSession, org_id: int
) -> list[OrgMemberResponse]:
    stmt = (
        select(
            OrgMember.id,
            OrgMember.user_id,
            OrgMember.role,
            OrgMember.joined_at,
            User.github_username.label("username"),
            User.display_name,
            User.avatar_url,
        )
        .join(User, OrgMember.user_id == User.id)
        .where(OrgMember.org_id == org_id)
        .order_by(OrgMember.joined_at)
    )
    result = await session.execute(stmt)
    return [
        OrgMemberResponse(
            id=row.id,
            user_id=row.user_id,
            username=row.username,
            display_name=row.display_name,
            avatar_url=row.avatar_url,
            role=row.role,
            joined_at=row.joined_at,
        )
        for row in result.all()
    ]


# -- Routes --


@router.post("", response_model=OrgDetailResponse, status_code=201)
async def create_org(
    body: OrgCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Create an organization. The creator is automatically added as owner."""
    # Check name uniqueness
    existing = await session.execute(
        select(Organization).where(Organization.name == body.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Organization name already taken")

    org = Organization(
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        avatar_url=body.avatar_url,
        owner_id=user.id,
    )
    session.add(org)
    await session.flush()

    # Auto-add creator as owner member
    owner_member = OrgMember(org_id=org.id, user_id=user.id, role="owner")
    session.add(owner_member)
    await session.commit()
    await session.refresh(org)
    await session.refresh(owner_member)

    return OrgDetailResponse(
        id=org.id,
        name=org.name,
        display_name=org.display_name,
        description=org.description,
        avatar_url=org.avatar_url,
        owner_id=org.owner_id,
        members=[
            OrgMemberResponse(
                id=owner_member.id,
                user_id=user.id,
                username=user.github_username,
                display_name=user.display_name,
                avatar_url=user.avatar_url,
                role="owner",
                joined_at=owner_member.joined_at,
            )
        ],
        created_at=org.created_at,
    )


@router.get("", response_model=list[OrgSummaryResponse])
async def list_orgs(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List organizations the current user is a member of."""
    stmt = (
        select(
            Organization.id,
            Organization.name,
            Organization.display_name,
            Organization.description,
            Organization.avatar_url,
            Organization.created_at,
            OrgMember.role,
            func.count(OrgMember.id).over(partition_by=Organization.id).label("member_count"),
        )
        .join(OrgMember, Organization.id == OrgMember.org_id)
        .where(OrgMember.user_id == user.id)
        .order_by(Organization.created_at.desc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    return [
        OrgSummaryResponse(
            id=row.id,
            name=row.name,
            display_name=row.display_name,
            description=row.description,
            avatar_url=row.avatar_url,
            member_count=row.member_count,
            role=row.role,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/{org_id}", response_model=OrgDetailResponse)
async def get_org(
    org_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get organization details with members."""
    org = await _get_org_or_404(session, org_id)
    await _require_membership(session, org_id, user.id)

    members = await _get_org_members(session, org_id)

    return OrgDetailResponse(
        id=org.id,
        name=org.name,
        display_name=org.display_name,
        description=org.description,
        avatar_url=org.avatar_url,
        owner_id=org.owner_id,
        members=members,
        created_at=org.created_at,
    )


@router.put("/{org_id}", response_model=OrgDetailResponse)
async def update_org(
    org_id: int,
    body: OrgUpdateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Update organization details (admin+ required)."""
    org = await _get_org_or_404(session, org_id)
    await _require_admin(session, org_id, user.id)

    if body.display_name is not None:
        org.display_name = body.display_name
    if body.description is not None:
        org.description = body.description
    if body.avatar_url is not None:
        org.avatar_url = body.avatar_url

    await session.commit()
    await session.refresh(org)

    members = await _get_org_members(session, org_id)

    return OrgDetailResponse(
        id=org.id,
        name=org.name,
        display_name=org.display_name,
        description=org.description,
        avatar_url=org.avatar_url,
        owner_id=org.owner_id,
        members=members,
        created_at=org.created_at,
    )


@router.delete("/{org_id}", status_code=204)
async def delete_org(
    org_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete an organization (owner only)."""
    org = await _get_org_or_404(session, org_id)
    await _require_owner(session, org_id, user.id)

    # Delete members and invitations (cascade should handle it, but be explicit)
    await session.execute(
        delete(OrgInvitation).where(OrgInvitation.org_id == org_id)
    )
    await session.execute(
        delete(OrgMember).where(OrgMember.org_id == org_id)
    )
    await session.delete(org)
    await session.commit()


@router.post("/{org_id}/invite", response_model=InviteResponse, status_code=201)
async def create_invite(
    org_id: int,
    body: InviteCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Generate an invite code for the organization (admin+ required)."""
    await _get_org_or_404(session, org_id)
    await _require_admin(session, org_id, user.id)

    expires_at = None
    if body.expires_in_hours is not None:
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            hours=body.expires_in_hours
        )

    invitation = OrgInvitation(
        org_id=org_id,
        inviter_id=user.id,
        invite_code=secrets.token_urlsafe(9),
        max_uses=body.max_uses,
        expires_at=expires_at,
    )
    session.add(invitation)
    await session.commit()
    await session.refresh(invitation)

    return InviteResponse(
        invite_code=invitation.invite_code,
        max_uses=invitation.max_uses,
        uses=invitation.uses,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


@router.post("/join/{code}", response_model=OrgMemberResponse, status_code=201)
async def join_org(
    code: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Accept an invitation and join an organization."""
    result = await session.execute(
        select(OrgInvitation).where(OrgInvitation.invite_code == code)
    )
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    # Check expiry
    if invitation.expires_at is not None:
        now = datetime.datetime.now(datetime.timezone.utc)
        if now > invitation.expires_at:
            raise HTTPException(status_code=410, detail="Invite has expired")

    # Check max uses
    if invitation.max_uses > 0 and invitation.uses >= invitation.max_uses:
        raise HTTPException(status_code=410, detail="Invite has reached max uses")

    # Check if already a member
    existing = await _get_membership(session, invitation.org_id, user.id)
    if existing:
        raise HTTPException(status_code=409, detail="Already a member of this organization")

    # Add member
    member = OrgMember(
        org_id=invitation.org_id, user_id=user.id, role="member"
    )
    session.add(member)

    # Increment uses
    invitation.uses += 1

    await session.commit()
    await session.refresh(member)

    return OrgMemberResponse(
        id=member.id,
        user_id=user.id,
        username=user.github_username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=member.role,
        joined_at=member.joined_at,
    )


@router.get("/{org_id}/members", response_model=list[OrgMemberWithMinisResponse])
async def list_members(
    org_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List organization members with their minis."""
    await _get_org_or_404(session, org_id)
    await _require_membership(session, org_id, user.id)

    # Get members
    member_stmt = (
        select(
            OrgMember.id,
            OrgMember.user_id,
            OrgMember.role,
            OrgMember.joined_at,
            User.github_username.label("username"),
            User.display_name,
            User.avatar_url,
        )
        .join(User, OrgMember.user_id == User.id)
        .where(OrgMember.org_id == org_id)
        .order_by(OrgMember.joined_at)
    )
    member_result = await session.execute(member_stmt)
    members = member_result.all()

    # Get all minis belonging to the org
    mini_stmt = select(
        Mini.id, Mini.username, Mini.display_name, Mini.avatar_url, Mini.owner_id
    ).where(Mini.org_id == org_id)
    mini_result = await session.execute(mini_stmt)
    minis = mini_result.all()

    # Group minis by owner
    minis_by_owner: dict[int, list[dict]] = {}
    for m in minis:
        owner_id = m.owner_id
        if owner_id is not None:
            minis_by_owner.setdefault(owner_id, []).append(
                {
                    "id": m.id,
                    "username": m.username,
                    "display_name": m.display_name,
                    "avatar_url": m.avatar_url,
                }
            )

    return [
        OrgMemberWithMinisResponse(
            id=row.id,
            user_id=row.user_id,
            username=row.username,
            display_name=row.display_name,
            avatar_url=row.avatar_url,
            role=row.role,
            joined_at=row.joined_at,
            minis=minis_by_owner.get(row.user_id, []),
        )
        for row in members
    ]


@router.delete("/{org_id}/members/{user_id}", status_code=204)
async def remove_member(
    org_id: int,
    user_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Remove a member from the organization (admin+ required, cannot remove owner)."""
    await _get_org_or_404(session, org_id)
    await _require_admin(session, org_id, user.id)

    target_member = await _get_membership(session, org_id, user_id)
    if not target_member:
        raise HTTPException(status_code=404, detail="Member not found")

    if target_member.role == "owner":
        raise HTTPException(status_code=403, detail="Cannot remove the organization owner")

    await session.delete(target_member)
    await session.commit()


@router.post("/{org_id}/teams", response_model=OrgTeamSummaryResponse, status_code=201)
async def create_org_team(
    org_id: int,
    body: OrgTeamCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a team within the organization (member+ required)."""
    await _get_org_or_404(session, org_id)
    await _require_membership(session, org_id, user.id)

    team = Team(
        name=body.name,
        description=body.description,
        owner_id=user.id,
        org_id=org_id,
        team_type="org",
    )
    session.add(team)
    await session.commit()
    await session.refresh(team)

    return OrgTeamSummaryResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        member_count=0,
        owner_username=user.github_username,
        created_at=team.created_at,
    )


@router.get("/{org_id}/teams", response_model=list[OrgTeamSummaryResponse])
async def list_org_teams(
    org_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List teams within the organization."""
    await _get_org_or_404(session, org_id)
    await _require_membership(session, org_id, user.id)

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
        .where(Team.org_id == org_id, Team.team_type == "org")
        .group_by(Team.id, User.github_username)
        .order_by(Team.created_at.desc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    return [
        OrgTeamSummaryResponse(
            id=row.id,
            name=row.name,
            description=row.description,
            member_count=row.member_count,
            owner_username=row.owner_username,
            created_at=row.created_at,
        )
        for row in rows
    ]
