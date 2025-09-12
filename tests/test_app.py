"""Integration tests use real files, real databases, HTTP routes and persistent sessions."""
import csv
import sqlite3
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.bootstrap import create_user
from app.db import AccessRequest, LoginSession, User, QualityRun, Audit, JobLease
from app.security import now, future

PASSWORD='A-test-password-123!'

@pytest.fixture
def env(tmp_path,database_url):
    settings=Settings(database_url,tmp_path/'sources',scan_interval=0)
    app=create_app(settings)
    with TestClient(app) as client:
        with app.state.factory() as db:
            for name,role,team in [('admin','admin','Platform'),('steward','steward','Customer Operations'),('analyst','analyst','Analytics'),('other','analyst','Analytics')]:
                create_user(db,name,PASSWORD,role,team)
        yield app,client,settings

def login(client,user='admin'):
    r=client.post('/api/login',json={'username':user,'password':PASSWORD})
    assert r.status_code==200,r.text
    return {'X-CSRF-Token':r.json()['csrf']}

def scan(client):
    headers=login(client)
    r=client.post('/api/scans',headers=headers)
    assert r.status_code==200,r.text
    return r.json()

def test_scan_real_sources_and_revenue(env):
    app,c,s=env
    assert scan(c)['status']=='passed'
    checks=c.get('/api/runs').json()[0]
    assert len(checks['results'])==11
    assert all(x['passed'] for x in checks['results'])
    rows=c.get('/api/assets/sales/preview').json()['rows']
    assert [r['revenue'] for r in rows]==['200','100']
    assert all('email' not in r for r in rows)
    assert c.get('/api/lineage').json()['run_id']==checks['id']
    assert c.get('/health/ready').status_code==200

def test_unauthenticated_api_and_data_not_public(env):
    _,c,_=env
    for url in ['/api/assets','/api/assets/customers/preview','/api/runs','/api/audit']:
        assert c.get(url).status_code==401
    assert c.get('/data/customers.csv').status_code==404
    assert c.get('/static/../runtime/sources/customers.csv').status_code==404

def test_access_request_approve_preview_revoke(env):
    app,c,_=env
    scan(c)
    h=login(c,'analyst')
    assert c.get('/api/assets/customers/preview').status_code==403
    r=c.post('/api/assets/customers/requests',json={'purpose':'Regional customer analysis'},headers=h)
    rid=r.json()['id']
    assert c.post('/api/assets/customers/requests',json={'purpose':'Regional customer analysis'},headers=h).status_code==409
    assert c.post(f'/api/requests/{rid}/decision',json={'action':'approve','note':'Self approval'},headers=h).status_code==403
    h=login(c,'steward')
    assert c.post(f'/api/requests/{rid}/decision',json={'action':'approve','note':'Approved for analysis'},headers=h).status_code==200
    login(c,'analyst')
    assert c.get('/api/assets/customers/preview').status_code==200
    h=login(c,'steward')
    assert c.post(f'/api/requests/{rid}/decision',json={'action':'revoke','note':'Purpose complete'},headers=h).status_code==200
    login(c,'analyst')
    assert c.get('/api/assets/customers/preview').status_code==403
    with app.state.factory() as db:
        assert db.query(Audit).filter_by(action='data.preview',actor='analyst').count()==1

def test_expired_approval_cannot_preview(env):
    app,c,_=env
    scan(c)
    with app.state.factory.begin() as db:
        db.add(AccessRequest(asset_id='customers',user_id='analyst',purpose='Expired business purpose',status='approved',expires='2000-01-01T00:00:00+00:00'))
    login(c,'analyst')
    assert c.get('/api/assets/customers/preview').status_code==403
    assert c.get('/api/requests').json()[0]['effective_status']=='expired'

def test_owner_scope_and_csrf_and_origin(env):
    _,c,_=env
    h=login(c,'steward')
    a=c.get('/api/assets/products').json()
    payload={'revision':a['revision'],'description':'A revised product description','classification':'internal','definitions':{x['name']:x['definition'] for x in a['columns']}}
    assert c.put('/api/assets/products',json=payload,headers=h).status_code==403
    assert c.post('/api/scans',headers=h).status_code==403
    assert c.get('/api/audit').status_code==403
    h=login(c)
    assert c.post('/api/scans').status_code==403
    assert c.post('/api/scans',headers={**h,'Origin':'https://evil.invalid'}).status_code==403
    assert c.post('/api/login',json={'username':'admin','password':PASSWORD},headers={'Origin':'https://evil.invalid'}).status_code==403

def test_metadata_version_and_optimistic_conflict(env):
    _,c,_=env
    h=login(c,'steward')
    a=c.get('/api/assets/customers').json()
    body={'revision':a['revision'],'description':'Customer master with revised business definition','classification':'confidential','definitions':{x['name']:x['definition'] for x in a['columns']}}
    assert c.put('/api/assets/customers',json=body,headers=h).status_code==200
    assert c.put('/api/assets/customers',json=body,headers=h).status_code==409
    versions=c.get('/api/assets/customers/versions').json()
    assert [v['revision'] for v in versions]==[2,1]
    assert versions[0]['document']['description']==body['description']

def test_source_failure_blocks_sales_without_destroying_history(env):
    _,c,s=env
    scan(c)
    with sqlite3.connect(s.data_dir/'operational.db') as db:
        db.execute("UPDATE orders SET customer_id='MISSING' WHERE order_id='O001'")
    result=scan(c)
    assert result['status']=='failed'
    assert c.get('/api/assets/sales/preview').status_code==409
    checks=c.get('/api/runs').json()
    assert checks[1]['status']=='passed'
    failure=next(x for x in checks[0]['results'] if x['rule']=='customer-reference')
    assert failure['failure_count']==1
    assert c.get('/api/assets/customers').json()['downstream']==['sales']
    assert c.get('/api/lineage').json()['run_id']==checks[1]['id']

def test_source_removed_does_not_silently_reseed(env):
    _,c,s=env
    scan(c)
    (s.data_dir/'customers.csv').rename(s.data_dir/'customers-away.csv')
    assert scan(c)['status']=='failed'
    assert c.get('/api/assets/customers').json()['status']=='source_error'
    assert c.get('/api/assets/sales/preview').status_code==409

def test_schema_drift_and_review_revokes_old_access(env):
    app,c,s=env
    scan(c)
    with app.state.factory.begin() as db:
        db.add(AccessRequest(asset_id='customers',user_id='analyst',purpose='Existing analysis',status='approved',expires=future(3600)))
    path=s.data_dir/'customers.csv'
    path.write_text('customer_id,email,region,new_field\nC001,alice@example.invalid,North,extra\nC002,bob@example.invalid,South,extra\n')
    assert scan(c)['status']=='failed'
    assert c.get('/api/assets/customers/preview').status_code==409
    h=login(c,'steward')
    a=c.get('/api/assets/customers').json()
    body={'revision':a['revision'],'definitions':{x:x+' business definition' for x in a['observed_columns']}}
    assert c.post('/api/assets/customers/schema/accept',json=body,headers=h).status_code==200
    a=c.get('/api/assets/customers').json()
    assert a['classification']=='confidential'
    assert a['columns'][-1]['classification']=='personal'
    assert scan(c)['status']=='passed'
    login(c,'analyst')
    assert c.get('/api/assets/customers/preview').status_code==403

def test_password_change_revokes_every_session(env):
    _,c,_=env
    h=login(c,'analyst')
    old_cookie=c.cookies.get('catalogue_session')
    login(c,'analyst')
    assert c.post('/api/password',json={'current_password':PASSWORD,'new_password':'Changed-password-123!'},headers={'X-CSRF-Token':c.get('/api/me').json()['csrf']}).status_code==200
    c.cookies.set('catalogue_session',old_cookie)
    assert c.get('/api/me').status_code==401
    assert c.post('/api/login',json={'username':'analyst','password':PASSWORD}).status_code==401

def test_lockout_persists(env):
    app,c,_=env
    for _ in range(5):
        assert c.post('/api/login',json={'username':'analyst','password':'wrong'}).status_code==401
    assert c.post('/api/login',json={'username':'analyst','password':PASSWORD}).status_code==429
    with app.state.factory() as db: assert db.get(User,'analyst').failed==5

def test_cross_user_request_privacy_and_rejection(env):
    _,c,_=env
    h=login(c,'analyst')
    rid=c.post('/api/assets/customers/requests',json={'purpose':'Private business purpose'},headers=h).json()['id']
    login(c,'other')
    assert c.get('/api/requests').json()==[]
    h=login(c,'steward')
    assert c.post(f'/api/requests/{rid}/decision',json={'action':'reject','note':'Purpose not approved'},headers=h).status_code==200
    assert c.post(f'/api/requests/{rid}/decision',json={'action':'approve','note':'Try decision again'},headers=h).status_code==409

def test_restart_preserves_runs_and_accounts(env):
    app,c,settings=env
    scan(c)
    second=create_app(settings)
    with TestClient(second) as new_client:
        login(new_client)
        assert len(new_client.get('/api/runs').json())==1
        assert new_client.get('/api/assets/sales/preview').status_code==200

def test_database_job_lease_prevents_overlap(env):
    app,c,_=env
    with app.state.factory.begin() as db:
        lease=db.get(JobLease,'pipeline');lease.expires=future(60);lease.owner='another-process'
    h=login(c)
    assert c.post('/api/scans',headers=h).status_code==409

def test_admin_creates_account_role_cannot_be_escalated(env):
    _,c,_=env
    body={'username':'new-user','password':PASSWORD,'role':'analyst','team':'Analytics'}
    h=login(c,'analyst')
    assert c.post('/api/users',json=body,headers=h).status_code==403
    h=login(c)
    assert c.post('/api/users',json=body,headers=h).status_code==200
    assert c.post('/api/users',json=body,headers=h).status_code==409
    assert c.post('/api/login',json={'username':'new-user','password':PASSWORD}).json()['role']=='analyst'

def test_scheduler_persists_run(tmp_path):
    app=create_app(Settings(f'sqlite:///{tmp_path/"scheduler.db"}',tmp_path/'sources',scan_interval=1))
    with TestClient(app):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            with app.state.factory() as db:
                count=db.query(QualityRun).filter_by(actor='scheduler',status='passed').count()
            if count: break
            time.sleep(.1)
        assert count>=1

def test_csv_onboarding_is_persistent_and_quality_checked(env):
    app,c,s=env
    payload={'asset_id':'suppliers','name':'Supplier master','description':'Supplier lookup for procurement analysis','owner_team':'Procurement','key_column':'supplier_id','csv_content':'supplier_id,name\nS001,Example supplier\nS002,Another supplier\n'}
    h=login(c,'analyst')
    assert c.post('/api/sources/csv',json=payload,headers=h).status_code==403
    h=login(c)
    result=c.post('/api/sources/csv',json=payload,headers=h)
    assert result.status_code==201,result.text
    assert c.get('/api/assets/suppliers/preview').status_code==409
    assert scan(c)['status']=='passed'
    assert c.get('/api/assets/suppliers/preview').json()['total_rows']==2
    asset=c.get('/api/assets/suppliers').json()
    assert asset['classification']=='confidential'
    assert all(x['classification']=='personal' for x in asset['columns'])
    assert c.post('/api/sources/csv',json=payload,headers=login(c)).status_code==409
    assert len(list(s.data_dir.glob('upload-*.csv')))==1
    assert len(c.get('/api/runs').json()[0]['results'])==13

def test_bad_csv_rejected_without_orphaned_files(env):
    _,c,s=env
    h=login(c)
    body={'asset_id':'suppliers','name':'Supplier master','description':'Supplier procurement source','owner_team':'Procurement','key_column':'supplier_id','csv_content':'supplier_id,name\nS001\n'}
    assert c.post('/api/sources/csv',json=body,headers=h).status_code==422
    assert not list(s.data_dir.glob('upload-*.csv'))

def test_removing_required_schema_field_requires_code_migration(env):
    _,c,s=env
    (s.data_dir/'customers.csv').write_text('customer_id,email\nC001,a@example.invalid\n')
    assert scan(c)['status']=='failed'
    a=c.get('/api/assets/customers').json()
    body={'revision':a['revision'],'definitions':{x:'Business definition' for x in a['observed_columns']}}
    assert c.post('/api/assets/customers/schema/accept',json=body,headers=login(c,'steward')).status_code==409

def test_initialization_never_recreates_missing_source_after_restart(env):
    _,c,s=env
    scan(c)
    path=s.data_dir/'customers.csv'
    path.unlink()
    app=create_app(s)
    with TestClient(app) as client:
        assert not path.exists()
        assert scan(client)['status']=='failed'
