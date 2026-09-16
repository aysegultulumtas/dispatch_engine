"""Idempotency-Key middleware against the in-memory store. The Postgres store's
reservation race (INSERT + IntegrityError) is covered in test_postgres_repository.py."""

import asyncio
import hashlib

import httpx2 as httpx
from fastapi.testclient import TestClient

from dispatch_engine.infra.idempotency import InMemoryIdempotencyStore

JOB = b'{"title":"Fix AC","skill":"hvac"}'
HEADERS = {"Content-Type": "application/json"}


def _post_job(client: TestClient, key: str, body: bytes = JOB) -> httpx.Response:
    return client.post("/jobs", content=body, headers={**HEADERS, "Idempotency-Key": key})


def test_same_key_replays_the_first_response_without_a_second_side_effect(
    client: TestClient,
) -> None:
    first = _post_job(client, "k1")
    second = _post_job(client, "k1")
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()
    assert len(client.get("/jobs").json()) == 1


def test_same_key_different_body_is_422(client: TestClient) -> None:
    assert _post_job(client, "k2").status_code == 201
    r = _post_job(client, "k2", body=b'{"title":"Other","skill":"hvac"}')
    assert r.status_code == 422
    assert "Idempotency-Key" in r.json()["detail"]


def test_key_still_in_progress_is_409(
    client: TestClient, idempotency_store: InMemoryIdempotencyStore
) -> None:
    # Reserve the key the way a concurrent first request would, then race it.
    request_hash = hashlib.sha256(b"/jobs\0" + JOB).hexdigest()
    assert asyncio.run(idempotency_store.reserve("k3", request_hash)) is None
    r = _post_job(client, "k3")
    assert r.status_code == 409
    assert "in progress" in r.json()["detail"]
    assert client.get("/jobs").json() == []


def test_failed_request_releases_the_key(client: TestClient) -> None:
    bad = _post_job(client, "k4", body=b'{"title":"","skill":"hvac"}')
    assert bad.status_code == 422  # Pydantic, not the middleware
    assert _post_job(client, "k4").status_code == 201  # same key, corrected body: not locked out


def test_without_header_nothing_is_cached(client: TestClient) -> None:
    client.post("/jobs", content=JOB, headers=HEADERS)
    client.post("/jobs", content=JOB, headers=HEADERS)
    assert len(client.get("/jobs").json()) == 2


def test_dispatch_run_replay_enqueues_once(client: TestClient) -> None:
    first = client.post("/dispatch-runs", headers={"Idempotency-Key": "run-1"})
    second = client.post("/dispatch-runs", headers={"Idempotency-Key": "run-1"})
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
