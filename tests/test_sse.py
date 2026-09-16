"""GET /dispatch-runs/{id}/events against the in-memory repository.

TestClient buffers a streamed response until the app finishes, so the status
changes are fired from timer threads while the stream is open — mutating the
same domain object the stream polls, which is what the worker does via Postgres."""

import asyncio
import json
import threading
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from dispatch_engine.api.routes import dispatch_runs
from dispatch_engine.domain import DispatchRun
from dispatch_engine.infra.memory import InMemoryRepository


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch_runs, "EVENT_POLL_INTERVAL", 0.01)


def _run(client: TestClient, repo: InMemoryRepository) -> DispatchRun:
    run_id = client.post("/dispatch-runs").json()["id"]
    run = asyncio.run(repo.get_dispatch_run(UUID(run_id)))
    assert run is not None
    return run


def _events(client: TestClient, run_id: UUID) -> list[dict[str, Any]]:
    with client.stream("GET", f"/dispatch-runs/{run_id}/events") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]


def _after(seconds: float, action: Callable[[], None]) -> None:
    threading.Timer(seconds, action).start()


def test_stream_emits_each_status_change_then_closes(
    client: TestClient, repo: InMemoryRepository
) -> None:
    run = _run(client, repo)
    _after(0.1, run.start)
    _after(0.3, lambda: run.succeed([]))

    events = _events(client, run.id)  # returns only because the terminal status closed it

    assert [e["status"] for e in events] == ["queued", "running", "succeeded"]
    assert events[-1] == client.get(f"/dispatch-runs/{run.id}").json()  # same JSON as polling


def test_already_finished_run_emits_once_and_closes(
    client: TestClient, repo: InMemoryRepository
) -> None:
    run = _run(client, repo)
    run.start()
    run.fail("boom")
    events = _events(client, run.id)
    assert [(e["status"], e["error"]) for e in events] == [("failed", "boom")]


def test_unknown_run_is_404(client: TestClient) -> None:
    r = client.get("/dispatch-runs/00000000-0000-0000-0000-000000000000/events")
    assert r.status_code == 404
