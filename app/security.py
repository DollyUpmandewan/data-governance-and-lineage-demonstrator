"""Passwords, opaque sessions and API authorization."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
from .db import User, LoginSession, Asset, AccessRequest, audit, now

def future(seconds): return (datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat()
def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def hash_password(password):
    salt = secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
    return f'pbkdf2_sha256${salt}${value}'
def verify(password, stored):
    try:
        _, salt, expected = stored.split('$')
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
        return hmac.compare_digest(actual, expected)
    except ValueError: return False

DUMMY = hash_password(secrets.token_urlsafe(24))

def identity(request: Request, db, write=False):
    token = request.cookies.get('catalogue_session', '')
    session = db.get(LoginSession, digest(token)) if token else None
    if not session or session.expires <= now(): raise HTTPException(401, 'Sign in to continue')
    user = db.get(User, session.user_id)
    if not user: raise HTTPException(401, 'Account unavailable')
    if write and not hmac.compare_digest(request.headers.get('x-csrf-token',''), session.csrf):
        raise HTTPException(403, 'Invalid request token; reload the page')
    return user, session

def manages(user, asset):
    return user.role == 'admin' or (user.role == 'steward' and user.team == asset.metadata_doc['owner']['team'])

def require_manager(user, asset):
    if not manages(user, asset): raise HTTPException(403, 'Only this asset owner or an administrator can do that')

def can_read(db, user, asset):
    if manages(user, asset): return True
    return any(r.status=='approved' and r.expires and r.expires > now() for r in db.query(AccessRequest).filter_by(asset_id=asset.id, user_id=user.id).all())
