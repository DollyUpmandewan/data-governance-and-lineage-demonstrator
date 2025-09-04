"""Initial catalogue schema.

Revision ID: 0001
"""
from alembic import op
import sqlalchemy as sa
revision='0001'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    # Explicit frozen schema: future model edits must use a new migration.
    op.create_table('users',sa.Column('id',sa.String(80),primary_key=True),sa.Column('password',sa.Text(),nullable=False),sa.Column('role',sa.String(20),nullable=False),sa.Column('team',sa.String(100),nullable=False),sa.Column('failed',sa.Integer(),nullable=False),sa.Column('locked_until',sa.String(40),nullable=False))
    op.create_table('sessions',sa.Column('token_hash',sa.String(64),primary_key=True),sa.Column('user_id',sa.String(80),sa.ForeignKey('users.id'),nullable=False),sa.Column('csrf',sa.String(80),nullable=False),sa.Column('expires',sa.String(40),nullable=False))
    op.create_table('assets',sa.Column('id',sa.String(80),primary_key=True),sa.Column('metadata_doc',sa.JSON(),nullable=False),sa.Column('records',sa.JSON(),nullable=False),sa.Column('observed_columns',sa.JSON(),nullable=False),sa.Column('status',sa.String(30),nullable=False),sa.Column('scanned_at',sa.String(40)),sa.Column('revision',sa.Integer(),nullable=False))
    op.create_table('metadata_versions',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('asset_id',sa.String(80),sa.ForeignKey('assets.id'),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('document',sa.JSON(),nullable=False),sa.Column('actor',sa.String(80),nullable=False),sa.Column('at',sa.String(40),nullable=False),sa.UniqueConstraint('asset_id','revision'))
    op.create_table('access_requests',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('asset_id',sa.String(80),sa.ForeignKey('assets.id'),nullable=False),sa.Column('user_id',sa.String(80),sa.ForeignKey('users.id'),nullable=False),sa.Column('purpose',sa.Text(),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('requested_at',sa.String(40),nullable=False),sa.Column('decided_by',sa.String(80)),sa.Column('decided_at',sa.String(40)),sa.Column('expires',sa.String(40)),sa.Column('note',sa.Text()))
    op.create_table('quality_runs',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('at',sa.String(40),nullable=False),sa.Column('actor',sa.String(80),nullable=False),sa.Column('status',sa.String(30),nullable=False),sa.Column('results',sa.JSON(),nullable=False),sa.Column('lineage',sa.JSON(),nullable=False),sa.Column('summary',sa.Text(),nullable=False))
    op.create_table('audit_events',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('at',sa.String(40),nullable=False),sa.Column('actor',sa.String(80),nullable=False),sa.Column('action',sa.String(80),nullable=False),sa.Column('resource',sa.String(120),nullable=False),sa.Column('details',sa.JSON(),nullable=False))
    op.create_table('job_leases',sa.Column('id',sa.String(30),primary_key=True),sa.Column('expires',sa.String(40),nullable=False),sa.Column('owner',sa.String(80),nullable=False))

def downgrade():
    for table in ['job_leases','audit_events','quality_runs','access_requests','metadata_versions','assets','sessions','users']: op.drop_table(table)
