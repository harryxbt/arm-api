"""add source_type and last_gameplay_ids to clip_extractions

Revision ID: 7b7f824fed22
Revises: e36740bce5d5
Create Date: 2026-03-22 23:23:18.943622

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b7f824fed22'
down_revision: Union[str, None] = 'e36740bce5d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clip_extractions', sa.Column('source_type', sa.Enum('youtube', 'instagram', 'upload', name='sourcetype'), server_default='youtube', nullable=False))
    op.add_column('clip_extractions', sa.Column('last_gameplay_ids', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('clip_extractions', 'last_gameplay_ids')
    op.drop_column('clip_extractions', 'source_type')
