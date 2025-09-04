"""Database entities shared by SQLite development and PostgreSQL deployment."""
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, Column, Integer, String, Text, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
def now(): return datetime.now(timezone.utc).isoformat()

class User(Base):
    __tablename__ = 'users'
    id = Column(String(80), primary_key=True)
    password = Column(Text, nullable=False)
    role = Column(String(20), nullable=False)
    team = Column(String(100), nullable=False)
    failed = Column(Integer, default=0, nullable=False)
    locked_until = Column(String(40), default='', nullable=False)

class LoginSession(Base):
    __tablename__ = 'sessions'
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(String(80), ForeignKey('users.id'), nullable=False)
    csrf = Column(String(80), nullable=False)
    expires = Column(String(40), nullable=False)

class Asset(Base):
    __tablename__ = 'assets'
    id = Column(String(80), primary_key=True)
    metadata_doc = Column(JSON, nullable=False)
    records = Column(JSON, nullable=False, default=list)
    observed_columns = Column(JSON, nullable=False, default=list)
    status = Column(String(30), nullable=False, default='unscanned')
    scanned_at = Column(String(40))
    revision = Column(Integer, nullable=False, default=1)

class Source(Base):
    __tablename__ = 'sources'
    asset_id = Column(String(80), ForeignKey('assets.id'), primary_key=True)
    kind = Column(String(20), nullable=False)
    location = Column(String(160), nullable=False)
    table_name = Column(String(80))

class MetadataVersion(Base):
    __tablename__ = 'metadata_versions'
    id = Column(Integer, primary_key=True)
    asset_id = Column(String(80), ForeignKey('assets.id'), nullable=False)
    revision = Column(Integer, nullable=False)
    document = Column(JSON, nullable=False)
    actor = Column(String(80), nullable=False)
    at = Column(String(40), nullable=False, default=now)
    __table_args__ = (UniqueConstraint('asset_id', 'revision'),)

class AccessRequest(Base):
    __tablename__ = 'access_requests'
    id = Column(Integer, primary_key=True)
    asset_id = Column(String(80), ForeignKey('assets.id'), nullable=False)
    user_id = Column(String(80), ForeignKey('users.id'), nullable=False)
    purpose = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    requested_at = Column(String(40), nullable=False, default=now)
    decided_by = Column(String(80))
    decided_at = Column(String(40))
    expires = Column(String(40))
    note = Column(Text)

class QualityRun(Base):
    __tablename__ = 'quality_runs'
    id = Column(Integer, primary_key=True)
    at = Column(String(40), nullable=False, default=now)
    actor = Column(String(80), nullable=False)
    status = Column(String(30), nullable=False)
    results = Column(JSON, nullable=False)
    lineage = Column(JSON, nullable=False)
    summary = Column(Text, nullable=False)

class Audit(Base):
    __tablename__ = 'audit_events'
    id = Column(Integer, primary_key=True)
    at = Column(String(40), nullable=False, default=now)
    actor = Column(String(80), nullable=False)
    action = Column(String(80), nullable=False)
    resource = Column(String(120), nullable=False)
    details = Column(JSON, nullable=False, default=dict)

class JobLease(Base):
    __tablename__ = 'job_leases'
    id = Column(String(30), primary_key=True)
    expires = Column(String(40), nullable=False)
    owner = Column(String(80), nullable=False)

class PurviewSync(Base):
    __tablename__ = 'purview_syncs'
    id = Column(Integer, primary_key=True)
    at = Column(String(40), nullable=False, default=now)
    finished_at = Column(String(40))
    actor = Column(String(80), nullable=False)
    status = Column(String(30), nullable=False)
    endpoint = Column(String(200), nullable=False)
    collection_id = Column(String(100), nullable=False)
    namespace = Column(String(64), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    entity_count = Column(Integer, nullable=False)
    verified_count = Column(Integer, nullable=False, default=0)
    remote_guids = Column(JSON, nullable=False, default=dict)
    summary = Column(Text, nullable=False)

def database(url):
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30} if url.startswith('sqlite') else {}, pool_pre_ping=True)
    if url.startswith('sqlite'):
        from sqlalchemy import event
        @event.listens_for(engine, 'connect')
        def sqlite_settings(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
    return engine, sessionmaker(bind=engine, expire_on_commit=False)

def audit(db, actor, action, resource, **details):
    db.add(Audit(actor=actor, action=action, resource=resource, details=details))
