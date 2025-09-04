"""Ensure concurrent requests cannot create multiple pending approvals.
Revision ID: 0002
"""
from alembic import op
import sqlalchemy as sa
revision='0002'
down_revision='0001'
branch_labels=None
depends_on=None

def upgrade():
    op.create_index('one_pending_request','access_requests',['asset_id','user_id'],unique=True,sqlite_where=sa.text("status = 'pending'"),postgresql_where=sa.text("status = 'pending'"))

def downgrade(): op.drop_index('one_pending_request',table_name='access_requests')
