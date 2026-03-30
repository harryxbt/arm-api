"""add publishing columns to cluster models

Revision ID: f0458e10c260
Revises: 3886a0f27cf2
Create Date: 2026-03-22 21:42:47.954628

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0458e10c260'
down_revision: Union[str, None] = '3886a0f27cf2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cluster_accounts', sa.Column('credentials', sa.JSON(), nullable=True))
    op.add_column('account_posts', sa.Column('job_id', sa.String(length=36), nullable=True))
    op.add_column('account_posts', sa.Column('video_storage_key', sa.String(length=500), nullable=True))
    op.add_column('account_posts', sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('account_posts', sa.Column('status', sa.Enum('pending', 'uploading', 'posted', 'failed', name='poststatus'), nullable=True))
    op.add_column('account_posts', sa.Column('platform_url', sa.String(length=500), nullable=True))
    op.add_column('account_posts', sa.Column('error_message', sa.Text(), nullable=True))
    op.add_column('account_posts', sa.Column('metadata', sa.JSON(), nullable=True))
    # SQLite does not support ALTER TABLE ADD CONSTRAINT; FKs declared in models but not enforced at DB level.


def downgrade() -> None:
    op.drop_column('account_posts', 'metadata')
    op.drop_column('account_posts', 'error_message')
    op.drop_column('account_posts', 'platform_url')
    op.drop_column('account_posts', 'status')
    op.drop_column('account_posts', 'scheduled_at')
    op.drop_column('account_posts', 'video_storage_key')
    op.drop_column('account_posts', 'job_id')
    op.drop_column('cluster_accounts', 'credentials')
