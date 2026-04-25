"""add evidence retention lifecycle metadata (MINI-223)

Revision ID: 20260425100000
Revises: 20260424153000, 20260424183000
Create Date: 2026-04-25 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260425100000"
down_revision: Union[str, tuple[str, str], None] = ("20260424153000", "20260424183000")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("retention_policy", sa.String(length=64), nullable=True))
    op.add_column(
        "evidence", sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "evidence", sa.Column("source_authorization", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "evidence",
        sa.Column("authorization_revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "evidence", sa.Column("access_classification", sa.String(length=32), nullable=True)
    )
    op.add_column("evidence", sa.Column("lifecycle_audit_json", sa.JSON(), nullable=True))
    op.create_index(
        op.f("ix_evidence_access_classification"),
        "evidence",
        ["access_classification"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_evidence_access_classification"), table_name="evidence")
    op.drop_column("evidence", "lifecycle_audit_json")
    op.drop_column("evidence", "access_classification")
    op.drop_column("evidence", "authorization_revoked_at")
    op.drop_column("evidence", "source_authorization")
    op.drop_column("evidence", "retention_expires_at")
    op.drop_column("evidence", "retention_policy")
