"""Contract tests simulate the documented Purview HTTP boundary, not a live Azure account."""
import copy
import json
from types import SimpleNamespace
from uuid import uuid5, NAMESPACE_URL

import httpx
import pytest
from fastapi.testclient import TestClient

from app.bootstrap import create_user
from app.config import Settings
from app.db import Asset, Audit, JobLease, PurviewSync
from app.main import create_app
from app.pipeline import run_pipeline
from app.purview import PurviewClient, PurviewError, DATASET, COLUMN, PROCESS, SCOPE, type_definitions
from app.purview_config import PurviewConfig
from app.security import future

PASSWORD = 'Purview-test-password-123'
TOKEN = 'SIMULATED-AZURE-TOKEN-NEVER-PERSIST'

class Credential:
    closed = False
    def get_token(self, scope):
        assert scope == SCOPE
        return SimpleNamespace(token=TOKEN)
    def close(self): self.closed = True


class DataMap:
    def __init__(self):
        self.types = {name: {'name': name} for name in ['DataSet', 'Process', 'Asset']}
        self.entities = {}
        self.requests = []
        self.reject = None
        self.corrupt = False
        self.throttle = 0
        self.wrong_lineage = False
        self.wrong_description = False

    def __call__(self, request):
        self.requests.append(request)
        assert request.headers['authorization'] == 'Bearer ' + TOKEN
        assert request.url.host == 'test-account.purview.azure.com'
        assert request.url.params['api-version'] == '2023-09-01'
        assert request.url.path.startswith('/datamap/api/atlas/v2/')
        path = request.url.path.split('/atlas/v2')[1]
        if self.reject:
            return httpx.Response(self.reject, json={'error': TOKEN + ' PRIVATE RAW BODY'})
        if self.throttle:
            self.throttle -= 1
            return httpx.Response(429, headers={'Retry-After': '0'}, json={'error': TOKEN})
        if path.startswith('/types/typedef/name/'):
            result = self.types.get(path.rsplit('/', 1)[1])
            return httpx.Response(200 if result else 404, json=result or {'error': 'not found'})
        if path == '/types/typedefs':
            assert request.method == 'POST'
            payload = json.loads(request.content)
            for definition in payload['entityDefs']:
                assert definition['name'] not in self.types
                self.types[definition['name']] = definition
            return httpx.Response(200, json=payload)
        if path == '/entity/bulk':
            assert request.method == 'POST'
            assert request.url.params['collectionId'] == 'demo-collection'
            payload = json.loads(request.content)
            for entity in payload['entities']:
                kind = entity['typeName']
                assert kind in self.types
                attrs = entity['attributes']
                defined = {x['name'] for x in self.types[kind]['attributeDefs']} | {'qualifiedName', 'name', 'description'}
                if kind == PROCESS: defined |= {'inputs', 'outputs'}
                assert set(attrs) <= defined
                self.entities[(kind, attrs['qualifiedName'])] = copy.deepcopy(entity) | {'guid': str(uuid5(NAMESPACE_URL, attrs['qualifiedName']))}
            return httpx.Response(200, json={'mutatedEntities': {}})
        if path.startswith('/entity/uniqueAttribute/type/'):
            kind = path.rsplit('/', 1)[1]
            qname = request.url.params['attr:qualifiedName']
            result = copy.deepcopy(self.entities[(kind, qname)])
            attrs = result['attributes']
            def resolve(ref):
                target = self.entities[(ref['typeName'], ref['uniqueAttributes']['qualifiedName'])]
                return {'guid': target['guid'], 'typeName': target['typeName']}
            if kind == COLUMN: attrs['dataset'] = resolve(attrs['dataset'])
            if kind == PROCESS:
                for side in ['inputs', 'outputs']: attrs[side] = [resolve(ref) for ref in attrs[side]]
                if self.wrong_lineage: attrs['outputs'] = []
            if self.corrupt: attrs['exportFingerprint'] = 'not-the-expected-snapshot'
            if self.wrong_description: attrs['description'] = 'Different persisted metadata'
            return httpx.Response(200, json={'entity': result})
        raise AssertionError('Unexpected Purview request: ' + str(request.url))


@pytest.fixture
def integration(tmp_path, database_url):
    config = PurviewConfig(enabled=True, endpoint='https://test-account.purview.azure.com', collection_id='demo-collection', namespace='test-workspace')
    settings = Settings(database_url, tmp_path/'sources', scan_interval=0, purview=config)
    app = create_app(settings)
    remote = DataMap()
    credentials = []
    def client_factory():
        credential = Credential()
        credentials.append(credential)
        return PurviewClient(config, credential=credential, transport=httpx.MockTransport(remote), sleep=lambda _: None)
    app.state.purview_client_factory = client_factory
    with TestClient(app) as client:
        with app.state.factory() as db:
            for name, role in [('admin', 'admin'), ('analyst', 'analyst'), ('steward', 'steward')]:
                create_user(db, name, PASSWORD, role, 'Customer Operations')
        yield app, client, config, remote, credentials


def sign_in(client, user='admin'):
    result = client.post('/api/login', json={'username': user, 'password': PASSWORD})
    assert result.status_code == 200
    return {'X-CSRF-Token': result.json()['csrf']}


def scan(app):
    return run_pipeline(app.state.factory, app.state.settings.data_dir, 'test')


def test_disabled_preview_works_without_credentials_or_network(integration):
    app, c, config, remote, creds = integration
    config.enabled = False
    headers = sign_in(c)
    assert scan(app)['status'] == 'passed'
    with app.state.factory.begin() as db:
        db.get(Asset, 'customers').records = [{'email': 'ROW-VALUES-MUST-NOT-LEAK'}]
    result = c.post('/api/purview/preview', headers=headers)
    assert result.status_code == 200
    plan = result.json()
    assert plan['network_used'] is False
    assert plan['entity_count'] == 19
    assert plan['counts'] == {DATASET: 4, COLUMN: 14, PROCESS: 1}
    assert 'ROW-VALUES-MUST-NOT-LEAK' not in result.text
    assert not remote.requests and not creds
    assert c.post('/api/purview/sync', headers=headers).status_code == 409
    assert c.post('/api/purview/test', headers=headers).status_code == 409
    assert not remote.requests and not creds


def test_repeat_publish_is_idempotent_and_read_back_verified(integration):
    app, c, _, remote, creds = integration
    headers = sign_in(c)
    scan(app)
    first = c.post('/api/purview/sync', headers=headers)
    assert first.status_code == 200, first.text
    second = c.post('/api/purview/sync', headers=headers)
    assert second.status_code == 200, second.text
    assert first.json()['remote_guids'] == second.json()['remote_guids']
    assert len(remote.entities) == 19
    assert second.json()['verified_count'] == 19
    assert sum(r.url.path.endswith('/types/typedefs') for r in remote.requests) == 1
    assert all(credential.closed for credential in creds)
    history = c.get('/api/purview/status').json()['history']
    assert [r['status'] for r in history] == ['succeeded', 'succeeded']
    assert TOKEN not in json.dumps(history)


def test_authorization_and_csrf_cover_all_routes(integration):
    _, c, _, remote, _ = integration
    assert c.get('/api/purview/status').status_code == 401
    for user in ['analyst', 'steward']:
        headers = sign_in(c, user)
        assert c.get('/api/purview/status').status_code == 403
        for path in ['preview', 'test', 'sync']:
            assert c.post('/api/purview/' + path, headers=headers).status_code == 403
    sign_in(c)
    for path in ['preview', 'test', 'sync']:
        assert c.post('/api/purview/' + path).status_code == 403
    assert not remote.requests


def test_connection_test_is_read_only(integration):
    _, c, _, remote, _ = integration
    result = c.post('/api/purview/test', headers=sign_in(c))
    assert result.status_code == 200
    assert result.json()['status'] == 'reachable'
    assert len(remote.requests) == 3
    assert all(r.method == 'GET' for r in remote.requests)
    assert not remote.entities


def test_permission_failure_is_durable_sanitized_and_unlocks(integration):
    app, c, _, remote, _ = integration
    remote.reject = 403
    result = c.post('/api/purview/sync', headers=sign_in(c))
    assert result.status_code == 502
    assert result.json()['status'] == 'failed'
    assert 'Data Curator' in result.json()['summary']
    assert TOKEN not in result.text
    with app.state.factory() as db:
        assert db.query(PurviewSync).one().status == 'failed'
        assert db.get(JobLease, 'purview').expires == ''
        assert db.query(Audit).filter_by(action='purview.publish_failed').count() == 1
        assert TOKEN not in str(db.query(PurviewSync).one().__dict__)


def test_readback_mismatch_cannot_be_reported_as_success(integration):
    app, c, _, remote, _ = integration
    scan(app)
    headers = sign_in(c)
    remote.corrupt = True
    failure = c.post('/api/purview/sync', headers=headers)
    assert failure.status_code == 502
    assert failure.json()['verified_count'] == 0
    remote.corrupt = False
    assert c.post('/api/purview/sync', headers=headers).json()['status'] == 'succeeded'
    assert len(remote.entities) == 19


def test_bad_remote_process_links_are_detected(integration):
    app, c, _, remote, _ = integration
    scan(app)
    remote.wrong_lineage = True
    result = c.post('/api/purview/sync', headers=sign_in(c))
    assert result.status_code == 502
    assert 'lineage' in result.json()['summary']


def test_correct_fingerprint_cannot_hide_wrong_remote_metadata(integration):
    _, c, _, remote, _ = integration
    remote.wrong_description = True
    result = c.post('/api/purview/sync', headers=sign_in(c))
    assert result.status_code == 502
    assert 'metadata fields differ' in result.json()['summary']


def test_throttling_retries_and_succeeds(integration):
    _, c, _, remote, _ = integration
    remote.throttle = 2
    assert c.post('/api/purview/sync', headers=sign_in(c)).status_code == 200
    assert remote.throttle == 0


def test_existing_incompatible_type_is_never_overwritten(integration):
    _, c, _, remote, _ = integration
    remote.types[DATASET] = {'name': DATASET, 'superTypes': ['DataSet'], 'attributeDefs': []}
    result = c.post('/api/purview/sync', headers=sign_in(c))
    assert result.status_code == 502
    assert 'incompatible' in result.json()['summary']
    assert all(r.method == 'GET' for r in remote.requests)


def test_preprovisioned_types_can_be_required(integration):
    _, c, config, remote, _ = integration
    config.create_types = False
    result = c.post('/api/purview/sync', headers=sign_in(c))
    assert result.status_code == 502
    assert 'missing' in result.json()['summary']
    assert not remote.entities


def test_no_process_is_exported_before_a_transformation_executes(integration):
    _, c, _, _, _ = integration
    plan = c.post('/api/purview/preview', headers=sign_in(c)).json()
    assert plan['lineage_run_id'] is None
    assert plan['counts'][PROCESS] == 0


def test_publish_lease_denies_overlap(integration):
    app, c, _, remote, _ = integration
    with app.state.factory.begin() as db:
        lease = db.get(JobLease, 'purview')
        lease.owner, lease.expires = 'other-worker', future(120)
    assert c.post('/api/purview/sync', headers=sign_in(c)).status_code == 409
    assert not remote.requests


def test_opt_in_scan_sync_does_not_change_scan_success(integration):
    app, c, config, remote, _ = integration
    config.sync_after_scan = True
    remote.reject = 403
    result = c.post('/api/scans', headers=sign_in(c))
    assert result.status_code == 200
    assert result.json()['status'] == 'passed'
    assert result.json()['purview']['status'] == 'failed'
    assert c.get('/api/assets/sales').json()['status'] == 'ready'


def test_credential_exception_details_are_not_returned(integration):
    app, c, _, _, _ = integration
    def fail(): raise RuntimeError(TOKEN + ' SECRET CONFIGURATION')
    app.state.purview_client_factory = fail
    result = c.post('/api/purview/sync', headers=sign_in(c))
    assert result.status_code == 502
    assert TOKEN not in result.text
    assert 'SECRET CONFIGURATION' not in result.text


@pytest.mark.parametrize('endpoint', [
    'http://localhost:8000', 'https://attacker.example',
    'https://real.purview.azure.com.attacker.example',
    'https://user:password@real.purview.azure.com',
    'https://real.purview.azure.com/path', 'https://real.purview.azure.com:443',
])
def test_credentials_cannot_be_sent_to_arbitrary_endpoints(endpoint):
    config = PurviewConfig(enabled=True, endpoint=endpoint, collection_id='demo')
    with pytest.raises(ValueError): PurviewClient(config, credential=Credential())


def test_network_errors_and_exhausted_throttle_are_safe():
    config = PurviewConfig(enabled=True, endpoint='https://test-account.purview.azure.com', collection_id='demo-collection')
    def fail(request): raise httpx.ConnectError(TOKEN, request=request)
    client = PurviewClient(config, credential=Credential(), transport=httpx.MockTransport(fail), sleep=lambda _: None)
    with pytest.raises(PurviewError) as error: client.check_connection()
    assert TOKEN not in str(error.value)
    client.close()

def test_historical_lineage_stays_labelled_after_source_failure(integration):
    from contextlib import closing
    import sqlite3
    app, c, _, _, _ = integration
    initial = scan(app)
    with closing(sqlite3.connect(app.state.settings.data_dir/'operational.db')) as source, source:
        source.execute("UPDATE orders SET customer_id='MISSING' WHERE order_id='O001'")
    assert scan(app)['status'] == 'failed'
    plan = c.post('/api/purview/preview', headers=sign_in(c)).json()
    process = next(e for e in plan['payload']['entities'] if e['typeName'] == PROCESS)
    assert process['attributes']['capturedRunId'] == initial['id']
    assert process['attributes']['currentOutputStatus'] == 'blocked'


def test_preview_is_an_explicit_metadata_allowlist(integration):
    app, c, _, _, _ = integration
    with app.state.factory.begin() as db:
        asset = db.get(Asset, 'customers')
        doc = dict(asset.metadata_doc)
        doc['unexpected_future_field'] = 'MUST-NOT-EXPORT-THIS'
        doc['path'] = 'C:/private/source-location'
        asset.metadata_doc = doc
    text = c.post('/api/purview/preview', headers=sign_in(c)).text
    assert 'MUST-NOT-EXPORT-THIS' not in text
    assert 'C:/private/source-location' not in text
    assert PASSWORD not in text


def test_exhausted_throttle_and_redirect_are_not_followed():
    config = PurviewConfig(enabled=True, endpoint='https://test-account.purview.azure.com', collection_id='demo-collection')
    for status in [429, 302]:
        requests = []
        def response(request):
            requests.append(request)
            return httpx.Response(status, headers={'Location': 'https://attacker.example', 'Retry-After': '0'}, json={'token': TOKEN})
        client = PurviewClient(config, credential=Credential(), transport=httpx.MockTransport(response), sleep=lambda _: None)
        with pytest.raises(PurviewError) as error: client.check_connection()
        assert TOKEN not in str(error.value)
        assert len(requests) == (3 if status == 429 else 1)
        assert all(r.url.host == 'test-account.purview.azure.com' for r in requests)
        client.close()


def test_invalid_remote_json_is_sanitized():
    config = PurviewConfig(enabled=True, endpoint='https://test-account.purview.azure.com', collection_id='demo-collection')
    client = PurviewClient(config, credential=Credential(), transport=httpx.MockTransport(lambda _: httpx.Response(200, text=TOKEN)), sleep=lambda _: None)
    with pytest.raises(PurviewError) as error: client.check_connection()
    assert TOKEN not in str(error.value)
    client.close()


def test_namespace_and_target_collection_required_before_network(integration):
    _, c, config, remote, _ = integration
    headers = sign_in(c)
    config.collection_id = ''
    assert c.post('/api/purview/sync', headers=headers).status_code == 409
    config.namespace = 'namespace with spaces'
    assert c.post('/api/purview/preview', headers=headers).status_code == 422
    assert not remote.requests

def test_invalid_endpoint_does_not_expose_embedded_credentials(integration):
    _, c, config, remote, _ = integration
    config.endpoint = 'https://user:PRIVATE-ENDPOINT-PASSWORD@test-account.purview.azure.com?key=PRIVATE-QUERY'
    sign_in(c)
    response = c.get('/api/purview/status')
    assert response.status_code == 200
    assert 'PRIVATE-ENDPOINT-PASSWORD' not in response.text
    assert 'PRIVATE-QUERY' not in response.text
    assert not response.json()['configured']
    assert not remote.requests
