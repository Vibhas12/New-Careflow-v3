"""agent run steps (v3.7): timed pipeline steps per AI agent run, for the Settings → AI agent pipeline view

Additive only (one nullable JSON column) – downgrade drops it; `alembic downgrade 0008` returns to v3.6.0's schema.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('agent_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('steps', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('agent_runs', schema=None) as batch_op:
        batch_op.drop_column('steps')
