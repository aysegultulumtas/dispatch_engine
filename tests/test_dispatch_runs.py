from fastapi.testclient import TestClient

from .conftest import FakeQueue


def test_create_dispatch_run_returns_202_and_enqueues(client: TestClient, queue: FakeQueue) -> None:
    r = client.post("/v1/dispatch-runs")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["assignments"] == []
    assert body["error"] is None
    assert len(queue.enqueued) == 1
    _func, run_id_arg = queue.enqueued[0]
    assert run_id_arg == body["id"]


def test_get_dispatch_run_returns_persisted_state(client: TestClient) -> None:
    created = client.post("/v1/dispatch-runs").json()
    r = client.get(f"/v1/dispatch-runs/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created


def test_get_unknown_dispatch_run_returns_404(client: TestClient) -> None:
    assert client.get("/v1/dispatch-runs/00000000-0000-0000-0000-000000000000").status_code == 404
