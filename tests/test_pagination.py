import asyncio
import base64

from fastapi.testclient import TestClient

from dispatch_engine.domain import Technician
from dispatch_engine.infra.memory import InMemoryRepository


def _job(client: TestClient) -> str:
    r = client.post("/v1/jobs", json={"title": "Fix AC", "skill": "hvac"})
    assert r.status_code == 201
    return str(r.json()["id"])


def test_cursor_chain_visits_every_job_exactly_once(client: TestClient) -> None:
    ids = {_job(client) for _ in range(5)}
    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        r = client.get("/v1/jobs", params=params)
        assert r.status_code == 200
        assert isinstance(r.json(), list)  # body stays a plain array for the UI
        assert len(r.json()) <= 2
        seen += [j["id"] for j in r.json()]
        cursor = r.headers.get("X-Next-Cursor")
        if cursor is None:
            break
    assert len(seen) == 5
    assert set(seen) == ids


def test_limit_is_capped_at_200_and_defaults_to_50(
    client: TestClient, repo: InMemoryRepository
) -> None:
    for i in range(201):
        asyncio.run(
            repo.add_technician(Technician(name=f"t{i}", max_jobs=1, skills=frozenset("x")))
        )

    r = client.get("/v1/technicians", params={"limit": 500})
    assert r.status_code == 200
    assert len(r.json()) == 200
    rest = client.get("/v1/technicians", params={"cursor": r.headers["X-Next-Cursor"]})
    assert len(rest.json()) == 1
    assert "X-Next-Cursor" not in rest.headers

    assert len(client.get("/v1/technicians").json()) == 50


def test_last_page_has_no_next_cursor(client: TestClient) -> None:
    _job(client)
    r = client.get("/v1/jobs")
    assert len(r.json()) == 1
    assert "X-Next-Cursor" not in r.headers


def test_malformed_cursor_or_limit_is_422(client: TestClient) -> None:
    assert client.get("/v1/jobs", params={"cursor": "not base64!"}).status_code == 422
    garbage = base64.urlsafe_b64encode(b"yesterday|not-a-uuid").decode()
    assert client.get("/v1/jobs", params={"cursor": garbage}).status_code == 422
    assert client.get("/v1/jobs", params={"limit": 0}).status_code == 422
