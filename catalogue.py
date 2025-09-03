"""Dependency-free local metadata catalogue. Python 3.10+."""
import argparse
import csv
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load(root=ROOT):
    return json.loads((root / 'catalogue/metadata.json').read_text())

def rows(asset, root=ROOT):
    path = (root / asset['path']).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Data path escapes catalogue root')
    with path.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        expected = [c['name'] for c in asset['columns']]
        if reader.fieldnames != expected:
            raise ValueError(f"{asset['id']}: CSV columns differ from metadata")
        return list(reader)

def validate(meta):
    assets = meta['assets']
    ids = [a['id'] for a in assets]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate asset IDs')
    index = {a['id']: a for a in assets}
    for a in assets:
        for key in ['name', 'description', 'source', 'path', 'classification', 'owner', 'access', 'columns', 'quality_rules', 'inputs']:
            if not a.get(key) and key != 'inputs':
                raise ValueError(f"{a['id']}: missing {key}")
        names = [c['name'] for c in a['columns']]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate column names')
        for c in a['columns']:
            if not c.get('definition') or not c.get('type') or not c.get('classification'):
                raise ValueError('Column documentation incomplete')
        for source in a['inputs']:
            if source not in index:
                raise ValueError('Unknown upstream asset')
        for r in a['quality_rules']:
            if r['column'] not in names or r['type'] not in ['unique','not_null','email','positive','foreign_key']:
                raise ValueError('Invalid quality rule')
            if r['type'] == 'foreign_key':
                target = index.get(r['target_asset'])
                if not target or r['target_column'] not in [c['name'] for c in target['columns']]:
                    raise ValueError('Invalid foreign key target')
    def visit(id, stack):
        if id in stack:
            raise ValueError('Lineage cycle')
        for source in index[id]['inputs']:
            visit(source, stack | {id})
    for id in ids:
        visit(id, set())
    for edge in meta['lineage']:
        target = index.get(edge['target'])
        if not target or edge['target_column'] not in [c['name'] for c in target['columns']] or not edge.get('transformation'):
            raise ValueError('Invalid lineage target')
        for source in edge['sources']:
            aid, column = source.split('.')
            if aid not in index or column not in [c['name'] for c in index[aid]['columns']] or aid not in target['inputs']:
                raise ValueError('Invalid lineage source')
    return index

def quality(meta, root=ROOT):
    index = validate(meta)
    tables = {id: rows(a, root) for id, a in index.items()}
    results = []
    for id, a in index.items():
        for r in a['quality_rules']:
            values = [row[r['column']] for row in tables[id]]
            failures = []
            seen = set()
            for n, value in enumerate(values, 2):
                kind = r['type']
                ok = True
                if kind == 'not_null': ok = bool(value and value.strip())
                elif kind == 'unique':
                    ok = bool(value) and value not in seen
                    seen.add(value)
                elif kind == 'email': ok = bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value or ''))
                elif kind == 'positive':
                    try:
                        number = Decimal(value)
                        ok = number.is_finite() and number > 0
                    except (InvalidOperation, TypeError): ok = False
                elif kind == 'foreign_key':
                    ok = bool(value) and value in {x[r['target_column']] for x in tables[r['target_asset']]}
                if not ok: failures.append(n)
            results.append({'asset': id, 'rule': r['id'], 'passed': not failures and bool(values), 'failed_csv_lines': failures, 'rows_checked': len(values)})
    return results

def build(root=ROOT):
    meta = load(root)
    index = validate(meta)
    customers = {r['customer_id']: r for r in rows(index['customers'], root)}
    products = {r['product_id']: r for r in rows(index['products'], root)}
    output = []
    for order in rows(index['orders'], root):
        customer = customers[order['customer_id']]
        product = products[order['product_id']]
        output.append({'order_id': order['order_id'], 'region': customer['region'], 'product_name': product['product_name'], 'revenue': str(Decimal(order['quantity']) * Decimal(product['price']))})
    with (root / 'data/sales.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[c['name'] for c in index['sales']['columns']])
        writer.writeheader()
        writer.writerows(output)
    return output

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['list','search','show','lineage','validate','build','quality','demo'])
    parser.add_argument('query', nargs='?', default='')
    args = parser.parse_args()
    try:
        meta = load()
        index = validate(meta)
        if args.command in ['build','demo']: build()
        if args.command in ['quality','demo']:
            results = quality(meta)
            print(json.dumps(results, indent=2))
            return 0 if all(r['passed'] for r in results) else 1
        if args.command == 'validate': print('Metadata valid: 4 assets' if len(index)==4 else f'Metadata valid: {len(index)} assets')
        elif args.command == 'build': print('Created data/sales.csv')
        elif args.command in ['list','search']:
            for a in meta['assets']:
                if args.command == 'list' or args.query.lower() in json.dumps(a).lower():
                    print(f"{a['id']}: {a['name']} | {a['owner']['team']} | {a['description']}")
        elif args.command == 'show': print(json.dumps(index[args.query], indent=2))
        elif args.command == 'lineage':
            if args.query and args.query not in index: raise ValueError('Unknown asset')
            print(json.dumps([e for e in meta['lineage'] if not args.query or e['target']==args.query or any(s.startswith(args.query+'.') for s in e['sources'])], indent=2))
        return 0
    except (ValueError, KeyError, OSError, InvalidOperation) as error:
        print(f'Error: {error}')
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
