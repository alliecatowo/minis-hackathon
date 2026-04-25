"""add AI contamination verdict provenance fields (MINI-208)

Revision ID: 20260425120000
Revises: 20260424153000, 20260424183000
Create Date: 2026-04-25 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260425120000"
down_revision: Union[str, None] = "20260425100000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("ai_contamination_confidence", sa.Float(), nullable=True))
    op.add_column(
        "evidence",
        sa.Column("ai_contamination_status", sa.String(length=32), nullable=True),
    )
    op.add_column("evidence", sa.Column("ai_contamination_reasoning", sa.Text(), nullable=True))
    op.add_column(
        "evidence",
        sa.Column("ai_contamination_provenance_json", sa.JSON(), nullable=True),
    )
    op.create_index(
        op.f("ix_evidence_ai_contamination_status"),
        "evidence",
        ["ai_contamination_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_evidence_ai_contamination_status"), table_name="evidence")
    op.drop_column("evidence", "ai_contamination_provenance_json")
    op.drop_column("evidence", "ai_contamination_reasoning")
    op.drop_column("evidence", "ai_contamination_status")
    op.drop_column("evidence", "ai_contamination_confidence")
