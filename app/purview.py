"""Microsoft Purview Data Map adapter. Only explicitly mapped metadata is exported."""
import hashlib
import json
import os
import time
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy.orm import load_only

from .db import Asset, QualityRun

DATASET = 'atlas_local_dataset_v1'
COLUMN = 'atlas_local_column_v1'
PROCESS = 'atlas_local_process_v1'
SCOPE = 'https://purview.azure.net/.default'
API_VERSION = '2023-09-01'
MAX_ENTITIES = 200


class PurviewError(Exception):
    """Safe public message; never include HTTP response bodies or credential errors."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def type_definitions():
    def definition(name, parent, fields):
        return {
            'name': name, 'superTypes': [parent], 'typeVersion': '1.0',
            'description': 'Atlas local governance connector metadata schema v1',
            'attributeDefs': [
                {'name': key, 'typeName': kind, 'isOptional': True, 'cardinality': 'SINGLE'}
                for key, kind in [*fields, ('exportFingerprint', 'string')]
            ],
        }
    return {'entityDefs': [
        definition(DATASET, 'DataSet', [
            ('localAssetId', 'string'), ('ownerTeam', 'string'), ('ownerContact', 'string'),
            ('sourceSystem', 'string'), ('sensitivity', 'string'), ('schemaJson', 'string'),
            ('accessPolicyJson', 'string'), ('qualityRulesJson', 'string'),
            ('qualitySummaryJson', 'string'), ('qualityStatus', 'string'),
            ('metadataRevision', 'int'), ('scannedAt', 'string'),
        ]),
        definition(COLUMN, 'Asset', [
            ('dataset', DATASET), ('dataType', 'string'), ('sensitivity', 'string'),
        ]),
        definition(PROCESS, 'Process', [
            ('columnLineageJson', 'string'), ('capturedRunId', 'int'),
            ('capturedAt', 'string'), ('currentOutputStatus', 'string'),
        ]),
    ]}


def build_export(db, config):
    config.validate(live=False)
    assets = db.query(Asset).options(load_only(
        Asset.id, Asset.metadata_doc, Asset.revision, Asset.status, Asset.scanned_at,
    )).order_by(Asset.id).all()
    latest = db.query(QualityRun).order_by(QualityRun.id.desc()).first()
    captured = next((r for r in db.query(QualityRun).order_by(QualityRun.id.desc()).yield_per(30) if r.lineage), None)
    prefix = f'atlas-local://{config.namespace}'
    names = {a.id: f'{prefix}/datasets/{quote(a.id, safe="")}' for a in assets}
    entities = []

    def reference(id):
        if id not in names:
            raise PurviewError('Captured lineage refers to an unknown dataset; review local metadata')
        return {'typeName': DATASET, 'uniqueAttributes': {'qualifiedName': names[id]}}

    def entity(kind, attrs):
        attrs['exportFingerprint'] = fingerprint(attrs)
        return {'typeName': kind, 'attributes': attrs, 'status': 'ACTIVE'}

    # Deliberately never read Asset.records, user accounts, sessions or access-request purposes.
    for asset in assets:
        doc = asset.metadata_doc
        columns = [{k: c[k] for k in ['name', 'definition', 'type', 'classification']} for c in doc['columns']]
        checks = [r for r in latest.results if r['asset'] == asset.id] if latest else []
        summary = {
            'runId': latest.id if latest else None,
            'checkedAt': latest.at if latest else None,
            'passedRules': sum(bool(r['passed']) for r in checks),
            'totalRules': len(checks),
            'failedRuleIds': [r['rule'] for r in checks if not r['passed']],
        }
        entities.append(entity(DATASET, {
            'qualifiedName': names[asset.id], 'name': doc['name'], 'description': doc['description'],
            'localAssetId': asset.id, 'ownerTeam': doc['owner']['team'],
            'ownerContact': doc['owner']['contact'], 'sourceSystem': doc['source'],
            'sensitivity': doc['classification'], 'schemaJson': canonical(columns),
            'accessPolicyJson': canonical(doc['access']),
            'qualityRulesJson': canonical(doc['quality_rules']), 'qualitySummaryJson': canonical(summary),
            'qualityStatus': asset.status, 'metadataRevision': asset.revision,
            'scannedAt': asset.scanned_at or '',
        }))
    for asset in assets:
        for column in asset.metadata_doc['columns']:
            entities.append(entity(COLUMN, {
                'qualifiedName': f'{names[asset.id]}/columns/{quote(column["name"], safe="")}',
                'name': column['name'], 'description': column['definition'],
                'dataset': reference(asset.id), 'dataType': column['type'],
                'sensitivity': column['classification'],
            }))
    if captured:
        # Only executed lineage is published; declared-but-unexecuted mappings are excluded.
        for target in sorted({e['target'] for e in captured.lineage}):
            edges = [e for e in captured.lineage if e['target'] == target]
            inputs = sorted({s.split('.', 1)[0] for e in edges for s in e['sources']})
            output = next((a for a in assets if a.id == target), None)
            if output is None:
                raise PurviewError('Captured lineage target no longer exists')
            entities.append(entity(PROCESS, {
                'qualifiedName': f'{prefix}/processes/{quote(target, safe="")}/v1',
                'name': f'Atlas {target} transformation',
                'description': 'Captured execution lineage. Current output health is recorded separately.',
                'inputs': [reference(id) for id in inputs], 'outputs': [reference(target)],
                'columnLineageJson': canonical(edges), 'capturedRunId': captured.id,
                'capturedAt': captured.at, 'currentOutputStatus': output.status,
            }))
    payload = {'entities': entities}
    if len(entities) > MAX_ENTITIES or len(canonical(payload).encode()) > 2_000_000:
        raise PurviewError('Export exceeds the small-project limit of 200 entities or 2 MB; partition the integration first')
    return {
        'payload': payload, 'type_definitions': type_definitions(), 'payload_hash': fingerprint(payload),
        'counts': {kind: sum(e['typeName'] == kind for e in entities) for kind in [DATASET, COLUMN, PROCESS]},
        'entity_count': len(entities), 'lineage_run_id': captured.id if captured else None,
    }


def azure_credential(config):
    from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
    if config.auth_mode == 'managed-identity':
        return ManagedIdentityCredential(client_id=os.getenv('AZURE_CLIENT_ID') or None,
                                         connection_timeout=5, read_timeout=10, retry_total=1)
    return DefaultAzureCredential(exclude_interactive_browser_credential=True, process_timeout=10,
                                  connection_timeout=5, read_timeout=10, retry_total=1)


class PurviewClient:
    def __init__(self, config, credential=None, transport=None, sleep=time.sleep):
        config.validate()
        self.config = config
        self.credential = credential if credential is not None else azure_credential(config)
        self.http = httpx.Client(transport=transport, timeout=20, follow_redirects=False)
        self.sleep = sleep
        self.deadline = time.monotonic() + 180

    def close(self):
        self.http.close()
        if hasattr(self.credential, 'close'):
            self.credential.close()

    def request(self, method, path, *, payload=None, params=None, allow_missing=False):
        query = {'api-version': API_VERSION, **(params or {})}
        for attempt in range(3):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise PurviewError('Purview operation exceeded its three-minute deadline; retry the same namespace')
            try:
                token = self.credential.get_token(SCOPE).token
            except Exception:
                raise PurviewError('Azure authentication failed. Check the configured identity and credentials.') from None
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise PurviewError('Azure token acquisition exceeded the publication deadline; retry after checking identity connectivity')
            try:
                response = self.http.request(
                    method, self.config.endpoint + '/datamap/api/atlas/v2' + path,
                    headers={'Authorization': 'Bearer ' + token}, params=query, json=payload,
                    timeout=min(20, remaining),
                )
            except httpx.RequestError:
                if attempt < 2:
                    self.sleep(attempt + 1)
                    continue
                raise PurviewError('Purview network request failed. Check networking, private endpoints and DNS.') from None
            if response.status_code == 404 and allow_missing:
                return None
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                try: delay = min(5, max(0, float(response.headers.get('Retry-After', attempt + 1))))
                except ValueError: delay = attempt + 1
                self.sleep(delay)
                continue
            if response.status_code not in {200, 201}:
                explanation = {
                    401: 'Azure token rejected; check the Purview token audience and identity.',
                    403: 'Purview permission denied; check Data Curator access on the target collection.',
                    409: 'Purview type or entity conflict; inspect the target type definitions.',
                    429: 'Purview throttled the request; retry later.',
                }.get(response.status_code, 'Purview rejected the request; inspect account configuration and API compatibility.')
                raise PurviewError(f'HTTP {response.status_code}: {explanation}')
            try:
                result = response.json()
            except ValueError:
                raise PurviewError('Purview returned an invalid JSON response') from None
            if not isinstance(result, dict):
                raise PurviewError('Purview returned an unexpected response structure')
            return result

    def check_connection(self):
        # Read-only; does not create custom types or entities.
        for name in ['DataSet', 'Process', 'Asset']:
            result = self.request('GET', '/types/typedef/name/' + name)
            if result.get('name') != name:
                raise PurviewError('Purview base type check returned an unexpected definition')
        return {'status': 'reachable', 'message': 'Authenticated Data Map type reads succeeded. Publish permission is checked when publishing.'}

    def ensure_types(self):
        missing = []
        for expected in type_definitions()['entityDefs']:
            existing = self.request('GET', '/types/typedef/name/' + expected['name'], allow_missing=True)
            if existing is None:
                missing.append(expected)
                continue
            actual_fields = {a['name']: a['typeName'] for a in existing.get('attributeDefs', [])}
            if not set(expected['superTypes']) <= set(existing.get('superTypes', [])) or any(
                actual_fields.get(a['name']) != a['typeName'] for a in expected['attributeDefs']
            ):
                raise PurviewError('Existing Atlas connector type is incompatible; do not overwrite it. Use a reviewed schema migration.')
        if missing:
            if not self.config.create_types:
                raise PurviewError('Connector types are missing. Provision them or enable PURVIEW_CREATE_TYPES.')
            self.request('POST', '/types/typedefs', payload={'entityDefs': missing})

    def publish(self, plan):
        self.ensure_types()
        entities = plan['payload']['entities']
        # Resolve parents before dependants. Unique attributes remain stable on repeated publishes.
        for kind in [DATASET, COLUMN, PROCESS]:
            group = [e for e in entities if e['typeName'] == kind]
            for offset in range(0, len(group), 50):
                self.request('POST', '/entity/bulk', payload={'entities': group[offset:offset + 50]},
                             params={'collectionId': self.config.collection_id})
        verified = {}
        remote_entities = {}
        for expected in entities:
            qname = expected['attributes']['qualifiedName']
            result = self.request('GET', '/entity/uniqueAttribute/type/' + expected['typeName'],
                                  params={'attr:qualifiedName': qname})
            remote = result.get('entity', {})
            attrs = remote.get('attributes', {})
            try: UUID(remote.get('guid', ''))
            except (ValueError, TypeError, AttributeError):
                raise PurviewError('Purview read-back did not return a valid entity GUID') from None
            if remote.get('status') != 'ACTIVE' or remote.get('typeName') != expected['typeName'] or attrs.get('qualifiedName') != qname or attrs.get('exportFingerprint') != expected['attributes']['exportFingerprint']:
                raise PurviewError('Purview read-back did not match the exported metadata snapshot; retry the sync')
            # A stored fingerprint is an identifier, not server-computed proof of every field.
            # Compare actual returned metadata as well as the fingerprint and graph links.
            if any(attrs.get(key) != value for key, value in expected['attributes'].items()
                   if key not in {'dataset', 'inputs', 'outputs'}):
                raise PurviewError('Purview read-back metadata fields differ from the exported snapshot; retry the sync')
            verified[qname] = remote['guid']
            remote_entities[qname] = remote
        for expected in entities:
            attrs = expected['attributes']
            remote = remote_entities[attrs['qualifiedName']]
            if expected['typeName'] == PROCESS:
                for side in ['inputs', 'outputs']:
                    wanted = {verified[r['uniqueAttributes']['qualifiedName']] for r in attrs[side]}
                    refs = remote.get('attributes', {}).get(side) or remote.get('relationshipAttributes', {}).get(side, [])
                    if {r.get('guid') for r in refs} != wanted:
                        raise PurviewError('Purview process lineage did not match its expected dataset links')
            elif expected['typeName'] == COLUMN:
                parent = remote.get('attributes', {}).get('dataset') or remote.get('relationshipAttributes', {}).get('dataset', {})
                if parent.get('guid') != verified[attrs['dataset']['uniqueAttributes']['qualifiedName']]:
                    raise PurviewError('Purview column parent did not match its dataset')
        return verified
