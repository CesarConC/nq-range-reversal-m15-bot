"""drop risk_pct from account

Revision ID: e5f8b2d1c4a6
Revises: d4e7a1b3c9f2
Create Date: 2026-06-27

risk_pct se define en la clase de estrategia (strategy.risk_pct), no en la cuenta.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'e5f8b2d1c4a6'
down_revision = 'd4e7a1b3c9f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.drop_column('risk_pct')


def downgrade() -> None:
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('risk_pct', sa.Float(), nullable=False, server_default='0.01')
        )
