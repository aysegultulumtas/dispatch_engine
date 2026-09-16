from fastapi.testclient import TestClient


def test_dispatch_and_complete_leave_an_audit_trail(client: TestClient) -> None:
    tech = client.post(
        "/v1/technicians", json={"name": "Ada", "max_jobs": 1, "skills": ["hvac"]}
    ).json()
    job = client.post("/v1/jobs", json={"title": "Fix AC", "skill": "hvac"}).json()
    assert client.get(f"/v1/jobs/{job['id']}/events").json() == []  # creation is not a transition

    client.post(f"/v1/jobs/{job['id']}/dispatch")
    client.post(f"/v1/jobs/{job['id']}/complete")

    events = client.get(f"/v1/jobs/{job['id']}/events").json()
    assert [(e["from_status"], e["to_status"], e["actor"]) for e in events] == [
        ("pending", "assigned", "api"),
        ("assigned", "completed", "api"),
    ]
    assert events[0]["technician_id"] == tech["id"]
    assert all(e["job_id"] == job["id"] for e in events)


def test_events_of_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/v1/jobs/00000000-0000-0000-0000-000000000000/events").status_code == 404
