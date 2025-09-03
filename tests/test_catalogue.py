import copy
import csv
import shutil
import tempfile
import unittest
from pathlib import Path
import catalogue

class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(catalogue.ROOT/'data', self.root/'data')
        shutil.copytree(catalogue.ROOT/'catalogue', self.root/'catalogue')
        self.meta = catalogue.load(self.root)
    def tearDown(self): self.tmp.cleanup()
    def change(self, asset, column, value):
        path = self.root/'data'/f'{asset}.csv'
        with path.open(newline='') as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            records = list(reader)
        records[1][column] = value
        with path.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
    def test_revenue_and_no_email(self):
        result = catalogue.build(self.root)
        self.assertEqual([r['revenue'] for r in result], ['200','100'])
        self.assertNotIn('email', result[0])
        self.assertTrue(all(r['passed'] for r in catalogue.quality(self.meta,self.root)))
    def test_bad_reference_detected(self):
        self.change('orders','customer_id','UNKNOWN')
        report = catalogue.quality(self.meta,self.root)
        self.assertEqual(next(r for r in report if r['rule']=='customer-reference')['failed_csv_lines'],[3])
    def test_duplicate_detected(self):
        self.change('customers','customer_id','C001')
        self.assertFalse(next(r for r in catalogue.quality(self.meta,self.root) if r['rule']=='customer-key')['passed'])
    def test_nonfinite_and_negative_rejected(self):
        for value in ['NaN','Infinity','-1','bad','0']:
            self.change('products','price',value)
            self.assertFalse(next(r for r in catalogue.quality(self.meta,self.root) if r['rule']=='price-positive')['passed'])
    def test_lineage_cycle_rejected(self):
        self.meta['assets'][0]['inputs']=['sales']
        with self.assertRaises(ValueError): catalogue.validate(self.meta)
    def test_unknown_lineage_column_rejected(self):
        self.meta['lineage'][0]['sources']=['orders.missing']
        with self.assertRaises(ValueError): catalogue.validate(self.meta)

if __name__ == '__main__': unittest.main()
