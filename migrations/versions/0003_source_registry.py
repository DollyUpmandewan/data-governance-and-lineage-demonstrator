"""Persist managed connector registrations.
Revision ID: 0003
"""
from alembic import op
import sqlalchemy as sa
revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('sources',sa.Column('asset_id',sa.String(80),sa.ForeignKey('assets.id'),primary_key=True),sa.Column('kind',sa.String(20),nullable=False),sa.Column('location',sa.String(160),nullable=False),sa.Column('table_name',sa.String(80)))

def downgrade(): op.drop_table('sources')
