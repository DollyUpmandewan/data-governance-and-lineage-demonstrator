"""Offline SQLite backup and non-overwriting restore for the local profile."""
from contextlib import closing

import argparse
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def snapshot(source, destination):
    with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(destination)) as backup:
        original.backup(backup)


def create(state:Path, archive:Path):
    if not (state/'catalogue.db').is_file(): raise ValueError('Local SQLite catalogue.db not found')
    if archive.exists(): raise ValueError('Backup destination already exists')
    archive.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        stage=Path(temporary)
        snapshot(state/'catalogue.db',stage/'catalogue.db')
        with closing(sqlite3.connect(stage/'catalogue.db')) as db:
            lease=db.execute("SELECT expires FROM job_leases WHERE id='pipeline'").fetchone()
            if lease and lease[0]>datetime.now(timezone.utc).isoformat(): raise ValueError('Scan is active; stop the server before backup')
        sources=state/'sources'
        if sources.exists():
            for original in sources.iterdir():
                if original.is_file() and original.suffix not in {'.db-wal','.db-shm'} and not original.name.endswith(('-wal','-shm')):
                    target=stage/'sources'/original.name
                    target.parent.mkdir(exist_ok=True)
                    if original.suffix=='.db': snapshot(original,target)
                    else: shutil.copy2(original,target)
        with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as output:
            for file in stage.rglob('*'):
                if file.is_file(): output.write(file,file.relative_to(stage))
    return archive


def restore(archive:Path,destination:Path):
    if destination.exists(): raise ValueError('Restore target must be a new directory')
    # Validate every member before extraction; do not permit traversal or symlinks.
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            resolved=(destination/member.filename).resolve()
            if not resolved.is_relative_to(destination.resolve()) or ((member.external_attr>>16)&0o170000)==0o120000: raise ValueError('Unsafe archive member')
        if 'catalogue.db' not in source.namelist(): raise ValueError('Not an Atlas SQLite backup')
        if sum(x.file_size for x in source.infolist())>200_000_000: raise ValueError('Backup exceeds local restore limit')
        source.extractall(destination)
    with closing(sqlite3.connect(destination/'catalogue.db')) as db, db:
        db.execute('DELETE FROM sessions')
        db.execute("UPDATE access_requests SET status='revoked',note='Restored backup; fresh owner approval required' WHERE status='approved'")
        db.execute("UPDATE job_leases SET expires='',owner=''")
        db.execute("UPDATE assets SET status='unscanned',records='[]'")
        db.execute('INSERT INTO audit_events(at,actor,action,resource,details) VALUES(?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),'offline-operator','backup.restored','workspace',json.dumps({'sessions_revoked':True,'grants_revoked':True})))
    return destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['create','restore'])
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    print(create(args.source,args.destination) if args.command=='create' else restore(args.source,args.destination))

if __name__=='__main__': main()
