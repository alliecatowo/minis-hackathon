"""add mini soul_prompt column

Revision ID: 20260508120000
Revises: 20260427090000
Create Date: 2026-05-08 12:00:00.000000

Splits the per-mini system prompt into two pieces:
- ``Mini.system_prompt`` (existing): legacy assembled blob (universal + soul)
- ``Mini.soul_prompt`` (new, this migration): per-mini cargo only

Chat assembly composes ``UNIVERSAL_MINI_PROMPT`` (constant in code) with the
per-mini ``soul_prompt`` at runtime. The legacy ``system_prompt`` column
stays nullable for now to avoid breaking older readers; a follow-up
migration will drop it once all consumers move to ``soul_prompt``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260508120000"
down_revision: Union[str, None] = "20260427090000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("minis", sa.Column("soul_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("minis", "soul_prompt")
