"""Atomic source scan, schema drift detection, quality gates and captured transformation lineage."""
import logging
import re
import secrets
from decimal import Decimal, InvalidOperation
from sqlalchemy import update
from fastapi import HTTPException
from .db import Asset, QualityRun, JobLease, audit, now
from .security import future
from .connectors import configured_sources

log = logging.getLogger(__name__)
# The same declared inputs drive transformation execution and recorded lineage.
SALES_MAPPING = [
    {'target':'sales','target_column':'order_id','sources':['orders.order_id'],'transformation':'copy'},
    {'target':'sales','target_column':'region','sources':['orders.customer_id','customers.customer_id','customers.region'],'transformation':'join customers on customer_id; copy region'},
    {'target':'sales','target_column':'product_name','sources':['orders.product_id','products.product_id','products.product_name'],'transformation':'join products on product_id; copy product_name'},
    {'target':'sales','target_column':'revenue','sources':['orders.quantity','orders.product_id','products.product_id','products.price'],'transformation':'join products on product_id; quantity * current price (INR)'},
]

def affected(assets, source):
    found = {source}
    while True:
        more = {a.id for a in assets if set(a.metadata_doc['inputs']) & found}
        if more <= found: return sorted(found-{source})
        found |= more

def evaluate(asset, records, tables):
    output = []
    for rule in asset.metadata_doc['quality_rules']:
        seen = set()
        failures = []
        target = {str(r.get(rule.get('target_column'),'')) for r in tables.get(rule.get('target_asset'),[])}
        for line, row in enumerate(records,2):
            value = str(row.get(rule['column'],'') or '')
            kind = rule['type']
            passed = False
            if kind == 'not_null': passed = bool(value.strip())
            elif kind == 'unique':
                passed = bool(value.strip()) and value not in seen
                seen.add(value)
            elif kind == 'foreign_key': passed = bool(value) and value in target
            elif kind == 'email': passed = bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value))
            elif kind == 'positive':
                try:
                    number = Decimal(value)
                    passed = number.is_finite() and number > 0
                except InvalidOperation: passed = False
            if not passed: failures.append(line)
        output.append({'asset':asset.id,'rule':rule['id'],'passed':bool(records) and not failures,'rows_checked':len(records),'failed_rows':failures[:100], 'failure_count':len(failures)})
    return output

def transform(tables):
    customers = {r['customer_id']:r for r in tables['customers']}
    products = {r['product_id']:r for r in tables['products']}
    return [{'order_id':o['order_id'],'region':customers[o['customer_id']]['region'],'product_name':products[o['product_id']]['product_name'],'revenue':str(Decimal(o['quantity'])*Decimal(products[o['product_id']]['price']))} for o in tables['orders']]

def run_pipeline(factory, data_dir, actor):
    # Database compare-and-set serializes scheduler/manual scans across processes.
    owner = secrets.token_hex(16)
    with factory.begin() as db:
        acquired = db.execute(update(JobLease).where(JobLease.id=='pipeline',JobLease.expires < now()).values(expires=future(300),owner=owner)).rowcount
        if acquired != 1: raise HTTPException(409,'A scan is already running')
    try:
        with factory.begin() as db:
            assets = db.query(Asset).order_by(Asset.id).all()
            index = {a.id:a for a in assets}
            tables, results, issues = {}, [], []
            for id, reader in configured_sources(db,data_dir).items():
                a = index[id]
                try:
                    columns, records = reader()
                    a.observed_columns = columns
                    if columns != [c['name'] for c in a.metadata_doc['columns']]:
                        a.status = 'schema_drift'
                        a.records = []
                        issues.append(f'{id}: schema changed; owner review required')
                        audit(db,actor,'schema.drift',id,expected=[c['name'] for c in a.metadata_doc['columns']],observed=columns)
                    else:
                        tables[id] = records
                        a.records = records
                        a.status = 'ready'
                    a.scanned_at = now()
                except Exception as error:
                    # Raw connector errors can include source values/paths: keep them out of API responses.
                    log.warning('Source scan failed for %s (%s)',id,type(error).__name__)
                    a.status, a.records = 'source_error', []
                    issues.append(f'{id}: source unavailable or connector limits exceeded')
            for id, records in tables.items():
                checks = evaluate(index[id],records,tables)
                results.extend(checks)
                if not all(r['passed'] for r in checks):
                    index[id].status = 'quality_failed'
                    issues.append(f'{id}: quality gate failed')
            sales = index['sales']
            captured = []
            if all(index[id].status == 'ready' for id in ['customers','products','orders']):
                sales.records = transform(tables)
                checks = evaluate(sales,sales.records,{**tables,'sales':sales.records})
                results.extend(checks)
                sales.status = 'ready' if all(r['passed'] for r in checks) else 'quality_failed'
                captured = SALES_MAPPING
                sales.scanned_at = now()
            else:
                sales.status, sales.records = 'blocked', []
                issues.append('sales: blocked by upstream source or quality failure')
            if sales.status == 'quality_failed': issues.append('sales: quality gate failed')
            run = QualityRun(actor=actor,status='failed' if issues else 'passed',results=results,lineage=captured,summary='; '.join(issues) if issues else f'All sources scanned; {len(results)} checks passed; sales refreshed')
            db.add(run)
            db.flush()
            audit(db,actor,'pipeline.finished',str(run.id),status=run.status,issues=issues)
            result = {'id':run.id,'status':run.status,'summary':run.summary}
        return result
    except Exception:
        with factory.begin() as db:
            db.add(QualityRun(actor=actor,status='error',results=[],lineage=[],summary='Pipeline execution error; inspect server logs'))
            for a in db.query(Asset): a.status, a.records = 'blocked', []
            audit(db,actor,'pipeline.error','pipeline')
        raise
    finally:
        with factory.begin() as db:
            db.execute(update(JobLease).where(JobLease.id=='pipeline',JobLease.owner==owner).values(expires='',owner=''))
