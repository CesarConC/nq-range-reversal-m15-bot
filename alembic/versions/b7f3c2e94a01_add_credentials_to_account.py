"""add_credentials_to_account

Revision ID: b7f3c2e94a01
Revises: 873530ec7cbe
Create Date: 2026-06-27 00:00:00.000000

Sustituye secrets_key por los campos de credenciales directos:
password, cid, secret, app_id, app_version, device_id.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = 'b7f3c2e94a01'
down_revision: Union[str, Sequence[str], None] = '873530ec7cbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.add_column(sa.Column('password', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('cid', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('secret', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('app_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='MyTradingBot'))
        batch_op.add_column(sa.Column('app_version', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='1.0'))
        batch_op.add_column(sa.Column('device_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='bot-device-001'))
        batch_op.drop_column('secrets_key')


def downgrade() -> None:
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.add_column(sa.Column('secrets_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        batch_op.drop_column('device_id')
        batch_op.drop_column('app_version')
        batch_op.drop_column('app_id')
        batch_op.drop_column('secret')
        batch_op.drop_column('cid')
        batch_op.drop_column('password')
