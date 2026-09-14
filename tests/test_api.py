from fastapi.testclient import TestClient


def _technician(client: TestClient, name: str = "Ada", max_jobs: int = 1) -> dict:
    r = client.post("/technicians", json={"name": name, "max_jobs": max_jobs, "skills": ["hvac"]})
    assert r.status_code == 201
    return r.json()


def _job(client: TestClient, skill: str = "hvac") -> dict:
    r = client.post("/jobs", json={"title": "Fix AC", "skill": skill})
    assert r.status_code == 201
    return r.json()


def test_health(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"


def test_malformed_payload_returns_422(client: TestClient) -> None:
    r = client.post("/technicians", json={"name": "Ada", "max_jobs": -1, "skills": []})
    assert r.status_code == 422


def test_dispatch_and_complete_flow(client: TestClient) -> None:
    tech, job = _technician(client), _job(client)
    r = client.post(f"/jobs/{job['id']}/dispatch")
    assert r.status_code == 200
    assert r.json()["status"] == "assigned"
    assert r.json()["technician_id"] == tech["id"]
    assert client.get("/technicians").json()[0]["load"] == 1
    r = client.post(f"/jobs/{job['id']}/complete")
    assert r.json()["status"] == "completed"
    assert client.get("/technicians").json()[0]["load"] == 0


def test_rule_violation_returns_409(client: TestClient) -> None:
    _technician(client, max_jobs=1)
    first, second = _job(client), _job(client)
    client.post(f"/jobs/{first['id']}/dispatch")
    r = client.post(f"/jobs/{second['id']}/dispatch")
    assert r.status_code == 409
    assert "no technician available" in r.json()["detail"]
    assert client.post(f"/jobs/{second['id']}/complete").status_code == 409


def test_unknown_job_returns_404(client: TestClient) -> None:
    assert client.get("/jobs/00000000-0000-0000-0000-000000000000").status_code == 404
