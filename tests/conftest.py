import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.rate_limit import RateLimiter


@pytest.fixture()
def test_session_factory():
    # StaticPool is required here: a plain sqlite:///:memory: engine hands out
    # a fresh, empty in-memory database on every new connection, so the schema
    # created below would be invisible to any session opened later. StaticPool
    # forces every connection to reuse the same single in-memory database.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def client(test_session_factory, monkeypatch):
    def override_get_db():
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.main.rate_limiter", RateLimiter(fake_redis))

    # Deliberately no `with` block: that would trigger the lifespan/startup
    # event, which calls init_db() against the real Postgres URL in settings.
    # Tests use their own SQLite schema created above instead.
    test_client = TestClient(app)

    yield test_client, test_session_factory

    app.dependency_overrides.clear()
