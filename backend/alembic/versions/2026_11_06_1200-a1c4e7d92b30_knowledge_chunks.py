"""knowledge chunks

Revision ID: a1c4e7d92b30
Revises: de7e788caacf
Create Date: 2026-11-06 12:00:00

"""
from typing import Sequence, Union

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa


revision: str = 'a1c4e7d92b30'
down_revision: Union[str, None] = 'de7e788caacf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table(
        'knowledge_chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=200), nullable=False),
        sa.Column('heading', sa.String(length=300), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('embedding', Vector(1024), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('content_hash'),
    )


def downgrade() -> None:
    op.drop_table('knowledge_chunks')
    # The vector extension is left installed: harmless, and it may have predated this
