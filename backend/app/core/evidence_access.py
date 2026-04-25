"""Enterprise evidence lifecycle access policy.

Raw evidence remains append-only. These helpers only decide whether derived
exports may leave the service based on explicit lifecycle metadata.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import Evidence

AUTHORIZED_SOURCE = "authorized"
EXPORTABLE_ACCESS_CLASSIFICATIONS = {"public", "company"}
EXPORTABLE_ACCESS_CLASSIFICATIONS_SQL = tuple(sorted(EXPORTABLE_ACCESS_CLASSIFICATIONS))
PRIVATE_SOURCE_PRIVACY = "private"


def evidence_export_block_reason(
    evidence: Evidence,
    *,
    now: datetime | None = None,
) -> str | None:
    """Return a block reason for evidence that must not participate in export."""
    now = now or datetime.now(timezone.utc)

    if not evidence.retention_policy:
        return "missing_retention_policy"
    if evidence.source_authorization != AUTHORIZED_SOURCE:
        return "source_not_authorized"
    if evidence.authorization_revoked_at is not None:
        return "source_authorization_revoked"
    if evidence.source_privacy == PRIVATE_SOURCE_PRIVACY:
        return "private_source"
    if evidence.access_classification not in EXPORTABLE_ACCESS_CLASSIFICATIONS:
        return "non_exportable_access_classification"
    if evidence.retention_expires_at is not None and evidence.retention_expires_at <= now:
        return "retention_expired"
    return None


def evidence_is_exportable(evidence: Evidence, *, now: datetime | None = None) -> bool:
    """True when evidence lifecycle metadata permits derived export."""
    return evidence_export_block_reason(evidence, now=now) is None


async def count_export_blocking_evidence(
    session: AsyncSession,
    mini_id: str,
    *,
    now: datetime | None = None,
) -> int:
    """Count evidence rows that fail closed for export/access boundaries."""
    now = now or datetime.now(timezone.utc)
    unsafe_filter = or_(
        Evidence.retention_policy.is_(None),
        Evidence.retention_policy == "",
        Evidence.source_authorization.is_(None),
        Evidence.source_authorization != AUTHORIZED_SOURCE,
        Evidence.authorization_revoked_at.is_not(None),
        Evidence.source_privacy == PRIVATE_SOURCE_PRIVACY,
        Evidence.access_classification.is_(None),
        Evidence.access_classification.notin_(EXPORTABLE_ACCESS_CLASSIFICATIONS_SQL),
        and_(
            Evidence.retention_expires_at.is_not(None),
            Evidence.retention_expires_at <= now,
        ),
    )
    result = await session.execute(
        select(func.count(Evidence.id)).where(Evidence.mini_id == mini_id, unsafe_filter)
    )
    return int(result.scalar_one())
