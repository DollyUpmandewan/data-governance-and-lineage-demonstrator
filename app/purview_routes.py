"""Administrator-only Purview operations and persistent publication evidence."""
import secrets
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import update

from .db import JobLease, PurviewSync, audit, now
from .purview import PurviewClient, PurviewError, build_export
from .security import identity, future


def sync_response(record):
    return {k: getattr(record, k) for k in [
        'id', 'at', 'finished_at', 'actor', 'status', 'endpoint', 'collection_id', 'namespace',
        'payload_hash', 'entity_count', 'verified_count', 'summary', 'remote_guids',
    ]}


def run_sync(factory, config, actor, client_factory):
    try:
        config.validate()
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    owner = secrets.token_hex(16)
    with factory.begin() as db:
        locked = db.execute(update(JobLease).where(
            JobLease.id == 'purview', JobLease.expires < now(),
        ).values(owner=owner, expires=future(600))).rowcount
        if locked != 1:
            raise HTTPException(409, 'Another Purview publish is already running')
    record_id = None
    try:
        with factory.begin() as db:
            db.query(PurviewSync).filter_by(status='running').update({
                'status': 'interrupted', 'finished_at': now(),
                'summary': 'Previous publish was interrupted. Remote entities may be partial; retry using the same namespace.',
            })
            plan = build_export(db, config)
            record = PurviewSync(
                actor=actor, status='running', endpoint=config.endpoint, collection_id=config.collection_id,
                namespace=config.namespace, payload_hash=plan['payload_hash'],
                entity_count=plan['entity_count'], verified_count=0, remote_guids={},
                summary='Publishing a metadata snapshot; no dataset rows are included.',
            )
            db.add(record)
            db.flush()
            record_id = record.id
            audit(db, actor, 'purview.publish_started', str(record_id), payload_hash=plan['payload_hash'])
        client = None
        verified = {}
        try:
            client = client_factory()
            verified = client.publish(plan)
            status, summary = 'succeeded', f'Published and read-back verified {len(verified)} metadata entities.'
        except PurviewError as error:
            status, summary = 'failed', str(error)
        except Exception:
            # Credential/HTTP exceptions can contain tokens, paths or response text.
            status, summary = 'failed', 'Purview publication failed unexpectedly. Check identity, networking and connector configuration.'
        finally:
            if client is not None:
                try: client.close()
                except Exception: pass
        with factory.begin() as db:
            record = db.get(PurviewSync, record_id)
            record.status, record.summary, record.finished_at = status, summary, now()
            record.verified_count, record.remote_guids = len(verified), verified
            audit(db, actor, 'purview.publish_' + status, str(record_id), verified_count=len(verified), summary=summary)
            result = sync_response(record)
        return result
    finally:
        with factory.begin() as db:
            db.execute(update(JobLease).where(JobLease.id == 'purview', JobLease.owner == owner).values(owner='', expires=''))


def router(factory, config):
    routes = APIRouter(prefix='/api/purview', tags=['Microsoft Purview'])

    def admin(request, db, write=False):
        user, _ = identity(request, db, write)
        if user.role != 'admin':
            raise HTTPException(403, 'Administrator access required')
        return user

    @routes.get('/status')
    def status(request: Request):
        with factory() as db:
            admin(request, db)
            config_error = ''
            try: config.validate(live=config.enabled)
            except ValueError as error: config_error = str(error)
            history = db.query(PurviewSync).order_by(PurviewSync.id.desc()).limit(20).all()
            return {
                'enabled': config.enabled, 'configured': config.enabled and not config_error,
                'endpoint': config.display_endpoint, 'collection_id': config.collection_id,
                'namespace': config.namespace, 'auth_mode': config.auth_mode,
                'sync_after_scan': config.sync_after_scan, 'create_types': config.create_types,
                'configuration_error': config_error,
                'history': [sync_response(r) for r in history],
            }

    @routes.post('/preview')
    def preview(request: Request):
        with factory.begin() as db:
            user = admin(request, db, True)
            try: plan = build_export(db, config)
            except (PurviewError, ValueError) as error: raise HTTPException(422, str(error)) from None
            audit(db, user.id, 'purview.export_previewed', 'catalogue', payload_hash=plan['payload_hash'])
            return {**plan, 'network_used': False,
                    'notice': 'Metadata only. Owner contacts and free-text definitions are included; review before publishing.'}

    @routes.post('/test')
    def test(request: Request):
        with factory() as db:
            user = admin(request, db, True)
            actor = user.id
        try: config.validate()
        except ValueError as error: raise HTTPException(409, str(error)) from None
        client = None
        try:
            client = request.app.state.purview_client_factory()
            result = client.check_connection()
        except PurviewError as error:
            result = {'status': 'failed', 'message': str(error)}
        except Exception:
            result = {'status': 'failed', 'message': 'Azure connection check failed; inspect server identity and configuration.'}
        finally:
            if client is not None:
                try: client.close()
                except Exception: pass
        with factory.begin() as db:
            audit(db, actor, 'purview.connection_checked', 'purview', status=result['status'])
        return JSONResponse(result, status_code=200 if result['status'] == 'reachable' else 502)

    @routes.post('/sync')
    def sync(request: Request):
        with factory() as db:
            user = admin(request, db, True)
            actor = user.id
        try:
            result = run_sync(factory, config, actor, request.app.state.purview_client_factory)
        except (PurviewError, ValueError) as error:
            raise HTTPException(422, str(error)) from None
        return JSONResponse(result, status_code=200 if result['status'] == 'succeeded' else 502)

    return routes
