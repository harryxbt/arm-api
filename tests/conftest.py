# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app

TEST_DB_URL = "postgresql://armageddon:armageddon@localhost:5432/armageddon_test"
test_engine = create_engine(TEST_DB_URL)
TestSession = sessionmaker(bind=test_engine)


@pytest.fixture
def setup_db():
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture
def db(setup_db):
    session = TestSession()
    yield session
    session.close()


@pytest.fixture
def client(setup_db):
    def override_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app)
    app.dependency_overrides.clear()
