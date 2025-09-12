import os
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

# PostgreSQL CI uses a separate disposable database per integration test.
# Local runs require no database service.

import pytest

@pytest.fixture
def database_url(tmp_path):
    service=os.getenv('TEST_DATABASE_URL')
    if not service:
        yield f'sqlite:///{tmp_path / "test.db"}'
        return
    name='atlas_test_'+uuid4().hex
    admin=create_engine(service,isolation_level='AUTOCOMMIT')
    with admin.connect() as connection: connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    try: yield str(make_url(service).set(database=name).render_as_string(hide_password=False))
    finally:
        with admin.connect() as connection: connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()
