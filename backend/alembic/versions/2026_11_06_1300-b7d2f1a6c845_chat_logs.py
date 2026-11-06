"""chat logs

Revision ID: b7d2f1a6c845
Revises: a1c4e7d92b30
Create Date: 2026-11-06 13:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7d2f1a6c845'
down_revision: Union[str, None] = 'a1c4e7d92b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ip_hash', sa.String(length=64), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('reply', sa.Text(), nullable=False),
        sa.Column('outcome', sa.String(length=20), nullable=False),
        sa.Column('tools_used', sa.JSON(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_chat_logs_at'), 'chat_logs', ['at'])
    op.create_index(op.f('ix_chat_logs_ip_hash'), 'chat_logs', ['ip_hash'])


def downgrade() -> None:
    op.drop_table('chat_logs')
