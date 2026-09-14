from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from dispatch_engine.api.app import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    # Fresh app per test: in-memory state never leaks between tests.
    with TestClient(create_app()) as c:
        yield c
