"""Seed a reversible failure in the managed synthetic source only."""
from contextlib import closing

import argparse
import sqlite3
from .config import Settings

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['break-reference','repair'])
    args=parser.parse_args()
    directory=Settings.from_env().data_dir
    if not (directory/'.synthetic-initialized').exists(): raise SystemExit('Synthetic source marker missing; refusing to modify data')
    with closing(sqlite3.connect(directory/'operational.db')) as connection, connection:
        if args.action=='break-reference':
            connection.execute("UPDATE orders SET customer_id='MISSING' WHERE order_id='O001' AND customer_id='C001'")
        else: connection.execute("UPDATE orders SET customer_id='C001' WHERE order_id='O001' AND customer_id='MISSING'")
    print('Synthetic source updated. Run a scan in Atlas to observe the result.')

if __name__=='__main__': main()
