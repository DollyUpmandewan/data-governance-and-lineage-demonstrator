import shutil
import sqlite3
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.db import AccessRequest, LoginSession, Asset, User
from app.bootstrap import create_user
from app.pipeline import run_pipeline
from app.backup import create, restore
from app.security import future


def test_local_backup_restore_and_permissions_reset(tmp_path):
    state=tmp_path/'state'
    state.mkdir()
    settings=Settings(f'sqlite:///{state/"catalogue.db"}',state/'sources',scan_interval=0)
    app=create_app(settings)
    with TestClient(app):
        with app.state.factory() as db:
            create_user(db,'reader','Backup-test-password','analyst','Analytics')
            db.add(LoginSession(token_hash='test-token-hash',user_id='reader',csrf='csrf',expires=future(3600)))
            db.add(AccessRequest(asset_id='customers',user_id='reader',purpose='Backup test purpose',status='approved',expires=future(3600)))
            db.commit()
        assert run_pipeline(app.state.factory,settings.data_dir,'test')['status']=='passed'
    archive=create(state,tmp_path/'backup.zip')
    restored=restore(archive,tmp_path/'restored')
    with sqlite3.connect(restored/'catalogue.db') as db:
        assert db.execute('SELECT count(*) FROM quality_runs').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
        assert db.execute('SELECT status FROM access_requests').fetchone()[0]=='revoked'
        assert db.execute("SELECT status FROM assets WHERE id='sales'").fetchone()[0]=='unscanned'
    with sqlite3.connect(restored/'sources/operational.db') as db:
        assert db.execute('SELECT count(*) FROM orders').fetchone()[0]==2
    with pytest.raises(ValueError): restore(archive,restored)


def test_restore_rejects_traversal_before_writing(tmp_path):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as output:
        output.writestr('catalogue.db',b'fake')
        output.writestr('../outside.txt','bad')
    with pytest.raises(ValueError): restore(archive,tmp_path/'restored')
    assert not (tmp_path/'outside.txt').exists()
    assert not (tmp_path/'restored').exists()
