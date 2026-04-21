"""add ai_contamination_score and ai_contamination_checked_at to evidence (ALLIE-433)

Revision ID: 20260420210000
Revises: 20260420200000
Create Date: 2026-04-20 21:00:00.000000

NOTE: Existing rows are NOT backfilled — they retain NULL scores.
Backfilling is tracked separately (ALLIE-434).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260420210000"
down_revision: Union[str, None] = "20260420200000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evidence",
        sa.Column("ai_contamination_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "evidence",
        sa.Column("ai_contamination_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evidence", "ai_contamination_checked_at")
    op.drop_column("evidence", "ai_contamination_score")
