"""remove refresh_tokens and legacy auth columns

Revision ID: a1b2c3d4e5f6
Revises: 23384e5bf831
Create Date: 2026-02-12 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '23384e5bf831'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the refresh_tokens table (Neon Auth manages sessions)
    op.drop_table('refresh_tokens')

    # Remove legacy auth columns from users table
    op.drop_column('users', 'github_id')
    op.drop_column('users', 'github_access_token')

    # Make github_username nullable (populated async after first login)
    op.alter_column('users', 'github_username',
                    existing_type=sa.String(255),
                    nullable=True)


def downgrade() -> None:
    # Restore github_username as non-nullable
    op.alter_column('users', 'github_username',
                    existing_type=sa.String(255),
                    nullable=False)

    # Restore legacy auth columns
    op.add_column('users', sa.Column('github_access_token', sa.String(1024), nullable=True))
    op.add_column('users', sa.Column('github_id', sa.Integer(), nullable=False))
    op.create_unique_constraint('uq_users_github_id', 'users', ['github_id'])

    # Recreate refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), default=False, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'])
