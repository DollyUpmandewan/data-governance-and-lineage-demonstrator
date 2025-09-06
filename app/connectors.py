"""Bounded read-only connectors. No user-provided SQL or filesystem paths."""
from contextlib import closing

import csv
import sqlite3

MAX_ROWS = 5000

def read_csv(path):
    if path.stat().st_size > 5_000_000: raise ValueError('CSV exceeds 5 MB connector limit')
    with path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if not columns or len(columns) != len(set(columns)): raise ValueError('Missing or duplicate CSV headers')
        rows = []
        for row in reader:
            if None in row or any(v is None for v in row.values()): raise ValueError('Malformed CSV row')
            rows.append(row)
            if len(rows) > MAX_ROWS: raise ValueError('CSV exceeds 5000 row connector limit')
        return columns, rows

def read_operational(path, table):
    if table not in {'products','orders'}: raise ValueError('Table not allowlisted')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as connection:
        cursor = connection.execute(f'SELECT * FROM "{table}" LIMIT {MAX_ROWS+1}')
        columns = [c[0] for c in cursor.description]
        rows = [dict(zip(columns, [str(v) if v is not None else '' for v in row])) for row in cursor.fetchall()]
        if len(rows) > MAX_ROWS: raise ValueError('Database table exceeds 5000 row connector limit')
        return columns, rows

def configured_sources(db, data_dir):
    from .db import Source
    output = {}
    for source in db.query(Source).all():
        path = (data_dir/source.location).resolve()
        if not path.is_relative_to(data_dir.resolve()): raise ValueError('Source path escapes managed storage')
        if source.kind == 'csv':
            output[source.asset_id] = lambda p=path: read_csv(p)
        elif source.kind == 'sqlite':
            output[source.asset_id] = lambda p=path,t=source.table_name: read_operational(p,t)
        else: raise ValueError('Unknown connector')
    return output
