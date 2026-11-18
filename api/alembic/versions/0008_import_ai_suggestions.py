"""import ai suggestions (multi-agent phase 5): stored suggestions of the extraction and column-mapping agents

Additive only (two nullable JSON columns) – downgrade drops them; `alembic downgrade 0007` returns to phase 4's schema.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ingestion_batches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_mapping', sa.JSON(), nullable=True))
    with op.batch_alter_table('ingestion_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_suggestion', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ingestion_records', schema=None) as batch_op:
        batch_op.drop_column('ai_suggestion')
    with op.batch_alter_table('ingestion_batches', schema=None) as batch_op:
        batch_op.drop_column('ai_mapping')
