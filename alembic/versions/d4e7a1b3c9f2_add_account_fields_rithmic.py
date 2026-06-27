"""add account fields rithmic

Revision ID: d4e7a1b3c9f2
Revises: b7f3c2e94a01
Create Date: 2026-06-27

Cambios:
- Elimina cid y secret (especificos de Tradovate)
- Renombra tradovate_env → environment (generico)
- Añade: system_name, account_type, prop_firm, daily_drawdown, account_cost, withdrawn_amount
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'd4e7a1b3c9f2'
down_revision = 'b7f3c2e94a01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('account', schema=None) as batch_op:
        # Eliminar columnas Tradovate
        batch_op.drop_column('cid')
        batch_op.drop_column('secret')
        # Renombrar tradovate_env → environment
        batch_op.alter_column('tradovate_env', new_column_name='environment')
        # Nuevas columnas con server_default para filas existentes
        batch_op.add_column(
            sa.Column('system_name', sa.String(), nullable=False, server_default='')
        )
        batch_op.add_column(
            sa.Column('account_type', sa.String(), nullable=False, server_default='evaluation')
        )
        batch_op.add_column(
            sa.Column('prop_firm', sa.String(), nullable=False, server_default='')
        )
        batch_op.add_column(
            sa.Column('daily_drawdown', sa.Float(), nullable=False, server_default='0.0')
        )
        batch_op.add_column(
            sa.Column('account_cost', sa.Float(), nullable=False, server_default='0.0')
        )
        batch_op.add_column(
            sa.Column('withdrawn_amount', sa.Float(), nullable=False, server_default='0.0')
        )


def downgrade() -> None:
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.drop_column('withdrawn_amount')
        batch_op.drop_column('account_cost')
        batch_op.drop_column('daily_drawdown')
        batch_op.drop_column('prop_firm')
        batch_op.drop_column('account_type')
        batch_op.drop_column('system_name')
        batch_op.alter_column('environment', new_column_name='tradovate_env')
        batch_op.add_column(
            sa.Column('cid', sa.String(), nullable=False, server_default='')
        )
        batch_op.add_column(
            sa.Column('secret', sa.String(), nullable=False, server_default='')
        )
