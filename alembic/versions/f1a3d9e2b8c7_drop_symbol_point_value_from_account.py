"""drop symbol and point_value from account

Revision ID: f1a3d9e2b8c7
Revises: e5f8b2d1c4a6
Create Date: 2026-06-27

symbol y point_value se mueven a la estrategia (BaseStrategy.symbol / .point_value).
Cada estrategia define el instrumento que opera; la cuenta no lo necesita.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a3d9e2b8c7'
down_revision = 'e5f8b2d1c4a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('account') as batch_op:
        batch_op.drop_column('symbol')
        batch_op.drop_column('point_value')


def downgrade() -> None:
    with op.batch_alter_table('account') as batch_op:
        batch_op.add_column(sa.Column('point_value', sa.Float(), nullable=False, server_default='2.0'))
        batch_op.add_column(sa.Column('symbol', sa.String(), nullable=False, server_default='MNQ'))