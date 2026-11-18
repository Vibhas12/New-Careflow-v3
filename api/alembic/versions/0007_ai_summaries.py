"""ai summaries (multi-agent phase 3): stored AI patient summary, one per patient

Additive only (a new table) – downgrade drops it; `alembic downgrade 0006` returns to phase 2's schema.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_summaries',
        sa.Column('patient_id', sa.String(length=16), sa.ForeignKey('patients.id', name='fk_ai_summaries_patient_id_patients', ondelete='CASCADE'), nullable=False),
        sa.Column('source_hash', sa.String(length=64), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('model', sa.String(length=80), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('generated_by', sa.String(length=32), sa.ForeignKey('users.id', name='fk_ai_summaries_generated_by_users', ondelete='SET NULL'), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('error_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('patient_id', name='pk_ai_summaries'),
    )


def downgrade() -> None:
    op.drop_table('ai_summaries')
