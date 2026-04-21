"""add ai_contamination_score and ai_contamination_checked_at to evidence (ALLIE-433)

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-04-20 00:00:00.000000

NOTE: Existing rows are NOT backfilled — they retain NULL scores.
Backfilling is tracked separately (ALLIE-434).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
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
