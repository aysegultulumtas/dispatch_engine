from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dispatch_engine.api.app import create_app
from dispatch_engine.api.deps import get_queue, get_repository
from dispatch_engine.infra.memory import InMemoryRepository


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
def client(queue: FakeQueue) -> Iterator[TestClient]:
    # Fresh app + in-memory repository per test: no Postgres needed for API tests,
    # keeps CI fast (Postgres-backed behavior is covered by test_postgres_repository.py).
    app = create_app()
    repo = InMemoryRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_queue] = lambda: queue
    with TestClient(app) as c:
        yield c
