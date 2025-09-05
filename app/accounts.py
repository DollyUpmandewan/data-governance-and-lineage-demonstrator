"""Create named accounts interactively. Passwords are not echoed or stored in files."""
import argparse
import getpass
import secrets
from app.config import Settings
from app.db import database
from app.bootstrap import create_user

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--demo',action='store_true',help='Create three local demo accounts with random passwords')
    parser.add_argument('--username')
    parser.add_argument('--role',choices=['admin','steward','analyst'],default='analyst')
    parser.add_argument('--team',default='Analytics')
    args=parser.parse_args()
    engine,factory=database(Settings.from_env().database_url)
    try:
        with factory() as db:
            if args.demo:
                for name,role,team in [('admin','admin','Platform'),('steward','steward','Customer Operations'),('analyst','analyst','Analytics')]:
                    password=secrets.token_urlsafe(18)
                    from app.db import User
                    if db.get(User,name):
                        print(f'{name}: already exists; password not changed')
                        continue
                    create_user(db,name,password,role,team)
                    print(f'{name} ({role}) password: {password}')
            else:
                if not args.username: parser.error('--username is required without --demo')
                create_user(db,args.username,getpass.getpass('New password (12+ characters): '),args.role,args.team)
                print('Account created')
    finally: engine.dispose()

if __name__=='__main__': main()
