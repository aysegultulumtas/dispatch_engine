"""Rate limiting. The unit `client` fixture overrides the dependency away; these
tests wire the real dependency to a real Redis (docker compose up -d redis) or
to an unreachable one, following the _unreachable policy of the other
integration tests."""

import os
from uuid import uuid4

import pytest
import redis
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from dispatch_engine.api.app import create_app
from dispatch_engine.api.deps import get_queue, get_repository
from dispatch_engine.infra.memory import InMemoryRepository
from dispatch_engine.infra.queue import REDIS_URL
from dispatch_engine.infra.ratelimit import CAPACITY, RedisTokenBucket

from .conftest import FakeQueue

IN_CI = bool(os.environ.get("CI"))


def _unreachable(reason: str) -> None:
    if IN_CI:
        pytest.fail(f"Redis required in CI but unreachable: {reason}")
    pytest.skip(f"Redis not reachable: {reason}")


def _limited_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    # A fresh key per test → a fresh bucket in Redis; the unit fixture's key would
    # keep its bucket between runs for ~2 minutes.
    api_key = f"rl-{uuid4()}"
    monkeypatch.setenv("API_KEY", api_key)
    app = create_app()
    repo = InMemoryRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_queue] = lambda: FakeQueue()
    client = TestClient(app)
    client.headers["X-API-Key"] = api_key
    return client, api_key


def test_bucket_empties_into_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        redis.Redis.from_url(REDIS_URL).ping()
    except redis.RedisError as exc:
        _unreachable(str(exc))
    client, _ = _limited_client(monkeypatch)
    with client:
        # The bucket refills at 1/s while we drain it, so drain until it answers 429
        # (bounded) rather than assuming exactly CAPACITY successes.
        statuses: list[int] = []
        for _ in range(CAPACITY + 30):
            r = client.get("/v1/jobs")
            statuses.append(r.status_code)
            if r.status_code == 429:
                break
        assert statuses.count(200) >= CAPACITY
        assert r.status_code == 429
        assert r.json()["detail"] == "rate limit exceeded"
        assert int(r.headers["Retry-After"]) >= 1
        assert client.get("/health").status_code == 200  # root endpoints are not limited


def test_redis_outage_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _limited_client(monkeypatch)
    client.app.state.rate_limiter = RedisTokenBucket(  # type: ignore[attr-defined]
        Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    )
    with client:
        assert client.get("/v1/jobs").status_code == 200  # allowed, with a warning logged
