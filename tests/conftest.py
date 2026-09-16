import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dispatch_engine.api.app import create_app
from dispatch_engine.api.deps import get_queue, get_repository
from dispatch_engine.infra.idempotency import InMemoryIdempotencyStore
from dispatch_engine.infra.memory import InMemoryRepository

TEST_API_KEY = "test-key"


@pytest.fixture(autouse=True, scope="session")
def api_key_env() -> Iterator[None]:
    # create_app() refuses to start without API_KEY (no default on purpose).
    previous = os.environ.get("API_KEY")
    os.environ["API_KEY"] = TEST_API_KEY
    yield
    if previous is None:
        del os.environ["API_KEY"]
    else:
        os.environ["API_KEY"] = previous


class FakeQueue:
    """Records enqueue() calls instead of talking to Redis/RQ. API tests only need
    to know a run was queued, not that a worker actually picked it up — that's
    covered by tests/test_worker.py against a real Redis+Postgres."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[Any, ...]] = []

    def enqueue(self, func: Any, *args: Any, **kwargs: Any) -> None:
        self.enqueued.append((func, *args))


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def idempotency_store() -> InMemoryIdempotencyStore:
    return InMemoryIdempotencyStore()


@pytest.fixture
def app(queue: FakeQueue, idempotency_store: InMemoryIdempotencyStore) -> FastAPI:
    # Fresh app + in-memory repository per test: no Postgres needed for API tests,
    # keeps CI fast (Postgres-backed behavior is covered by test_postgres_repository.py).
    app = create_app()
    repo = InMemoryRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_queue] = lambda: queue
    app.state.idempotency_store = idempotency_store
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        c.headers["X-API-Key"] = TEST_API_KEY  # every test is authenticated unless it opts out
        yield c
