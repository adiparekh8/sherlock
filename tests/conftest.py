import os
from pathlib import Path
import tempfile

os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='sherlock-test-')
os.environ['DATABASE_URL'] = os.environ.get('TEST_DATABASE_URL', 'sqlite:///' + os.environ['DATA_DIR'] + '/test.db')
import pytest
from app.db import Base, engine, Session, Refund, Allocation
from app.seed import generate
from app.engine import ingest, propose

@pytest.fixture(scope='session')
def fixtures(): return generate()

@pytest.fixture
def seeded(fixtures):
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    paths,total=fixtures
    with Session.begin() as s:
        s.add(Refund(id=1,amount=total,importer='Bay Supply Imports',date='2026-11-06'))
        s.add(Allocation(id='unallocated',amount=total,chain={},evidence=[],reason='Awaiting processing',issues=[],obligation={}))
        s.flush()
        for path in paths: ingest(s,path)
        propose(s)
    return total
