import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dispatch_engine.api.app import create_app


def test_missing_key_is_401(app: FastAPI) -> None:
    with TestClient(app) as anonymous:
        r = anonymous.get("/technicians")
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid or missing API key"


def test_wrong_key_is_401(client: TestClient) -> None:
    r = client.post("/jobs", json={"title": "x", "skill": "hvac"}, headers={"X-API-Key": "nope"})
    assert r.status_code == 401


def test_health_ready_and_docs_stay_open(app: FastAPI) -> None:
    with TestClient(app) as anonymous:
        assert anonymous.get("/health").status_code == 200
        assert anonymous.get("/docs").status_code == 200
        assert anonymous.get("/openapi.json").status_code == 200
        # /ready pings real dependencies; either answer is fine, just not 401.
        assert anonymous.get("/ready").status_code in (200, 503)


def test_openapi_declares_the_security_scheme(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    scheme = spec["components"]["securitySchemes"]["APIKeyHeader"]
    assert scheme == {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    assert spec["paths"]["/technicians"]["get"]["security"] == [{"APIKeyHeader": []}]
    assert "security" not in spec["paths"]["/health"]["get"]


def test_app_refuses_to_start_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_KEY")
    assert "API_KEY" not in os.environ
    with pytest.raises(RuntimeError, match="API_KEY"):
        create_app()
