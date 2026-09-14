from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from dispatch_engine.api.app import create_app
from dispatch_engine.api.deps import get_repository
from dispatch_engine.infra.memory import InMemoryRepository


@pytest.fixture
def client() -> Iterator[TestClient]:
    # Fresh app + in-memory repository per test: no Postgres needed for API tests,
    # keeps CI fast (Postgres-backed behavior is covered by test_postgres_repository.py).
    app = create_app()
    repo = InMemoryRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    with TestClient(app) as c:
        yield c
