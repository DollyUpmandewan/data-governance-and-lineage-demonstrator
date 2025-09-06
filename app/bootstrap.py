"""Initial metadata and synthetic operational source setup; never overwrites existing records."""
from contextlib import closing

import csv
import json
import shutil
import sqlite3
from pathlib import Path
from .db import Asset, MetadataVersion, JobLease, User, Source, audit
from .security import hash_password

ROOT = Path(__file__).resolve().parent.parent

def initialize_sources(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    marker = data_dir/'.synthetic-initialized'
    if marker.exists(): return
    csv_path = data_dir/'customers.csv'
    if not csv_path.exists(): shutil.copy(ROOT/'data/customers.csv', csv_path)
    path = data_dir/'operational.db'
    if not path.exists():
        with closing(sqlite3.connect(path)) as connection, connection:
            for table in ['products','orders']:
                with (ROOT/'data'/f'{table}.csv').open(newline='') as stream:
                    reader = csv.DictReader(stream)
                    columns = reader.fieldnames
                    connection.execute(f'CREATE TABLE {table} ('+', '.join(f'"{c}" TEXT' for c in columns)+')')
                    connection.executemany(f'INSERT INTO {table} VALUES ('+','.join('?' for c in columns)+')', [tuple(r[c] for c in columns) for r in reader])
    marker.write_text('Synthetic source fixtures initialized once. Missing files are treated as failures.\n')

def seed(db):
    if not db.get(JobLease, 'pipeline'): db.add(JobLease(id='pipeline', expires='', owner=''))
    meta = json.loads((ROOT/'catalogue/metadata.json').read_text())
    for doc in meta['assets']:
        if db.get(Asset, doc['id']): continue
        doc['source'] = {'customers':'CSV • CRM export','products':'SQLite • operational.products','orders':'SQLite • operational.orders','sales':'Managed sales transformation v1'}[doc['id']]
        doc['access']['approved_roles'] = ['owner approval required']
        doc['access']['controls'] = ['Preview requires an active approved request or asset ownership','External source permissions are managed separately']
        doc['access']['retention'] = 'Review every 90 days; deletion requires an approved operational process'
        db.add(Asset(id=doc['id'], metadata_doc=doc, records=[], observed_columns=[], status='unscanned'))
        db.flush()
        db.add(MetadataVersion(asset_id=doc['id'], revision=1, document=doc, actor='bootstrap'))
    for id in ['customers','products','orders']:
        if not db.get(Source,id): db.add(Source(asset_id=id,kind='csv' if id=='customers' else 'sqlite',location='customers.csv' if id=='customers' else 'operational.db',table_name=None if id=='customers' else id))
    db.commit()

def create_user(db, name, password, role, team):
    if role not in {'admin','steward','analyst'}: raise ValueError('Invalid role')
    if len(password) < 12: raise ValueError('Password needs at least 12 characters')
    if db.get(User,name): raise ValueError('User already exists')
    db.add(User(id=name,password=hash_password(password),role=role,team=team))
    audit(db,'bootstrap','user.created',name,role=role,team=team)
    db.commit()
