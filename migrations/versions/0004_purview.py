"""Persist Purview sync evidence and serialize publishers.
Revision ID: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('purview_syncs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('at', sa.String(40), nullable=False),
        sa.Column('finished_at', sa.String(40)),
        sa.Column('actor', sa.String(80), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('endpoint', sa.String(200), nullable=False),
        sa.Column('collection_id', sa.String(100), nullable=False),
        sa.Column('namespace', sa.String(64), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('entity_count', sa.Integer(), nullable=False),
        sa.Column('verified_count', sa.Integer(), nullable=False),
        sa.Column('remote_guids', sa.JSON(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
    )
    op.execute("INSERT INTO job_leases(id,expires,owner) VALUES ('purview','','')")


def downgrade():
    op.execute("DELETE FROM job_leases WHERE id='purview'")
    op.drop_table('purview_syncs')
