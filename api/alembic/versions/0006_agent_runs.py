"""agent runs (multi-agent phase 1): one row per requested AI agent run

Additive only (a new table) – downgrade drops it and leaves every other table untouched, so
`alembic downgrade 0005` returns the schema exactly to CareFlow V3.0.0.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('agent', sa.String(length=40), nullable=False),
        sa.Column('user_id', sa.String(length=32), sa.ForeignKey('users.id', name='fk_agent_runs_user_id_users', ondelete='SET NULL'), nullable=True),
        sa.Column('patient_id', sa.String(length=16), nullable=True),
        sa.Column('entity', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('model', sa.String(length=80), nullable=True),
        sa.Column('attempts', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('error_code', sa.Integer(), nullable=True),
        sa.Column('issues', sa.JSON(), nullable=True),
        sa.Column('input_hash', sa.String(length=64), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.CheckConstraint("status IN ('ok','failed','withheld','blocked','limited','disabled')", name='ck_agent_runs_status'),
        sa.PrimaryKeyConstraint('id', name='pk_agent_runs'),
    )
    op.create_index('ix_agent_runs_created_at', 'agent_runs', ['created_at'])
    op.create_index('ix_agent_runs_agent', 'agent_runs', ['agent'])
    op.create_index('ix_agent_runs_user_id', 'agent_runs', ['user_id'])
    op.create_index('ix_agent_runs_patient_id', 'agent_runs', ['patient_id'])


def downgrade() -> None:
    op.drop_index('ix_agent_runs_patient_id', table_name='agent_runs')
    op.drop_index('ix_agent_runs_user_id', table_name='agent_runs')
    op.drop_index('ix_agent_runs_agent', table_name='agent_runs')
    op.drop_index('ix_agent_runs_created_at', table_name='agent_runs')
    op.drop_table('agent_runs')
