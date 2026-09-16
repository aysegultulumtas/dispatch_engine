import uuid

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.trace import ProxyTracerProvider

from dispatch_engine.observability import configure_tracing


def test_request_id_is_echoed_when_given(client: TestClient) -> None:
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"


def test_request_id_is_generated_when_missing(client: TestClient) -> None:
    r = client.get("/health")
    uuid.UUID(r.headers["X-Request-ID"])  # a fresh uuid4, not empty


def test_tracing_stays_off_without_the_standard_otel_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    configure_tracing()
    # No provider installed → no exporter trying (and failing) to reach localhost:4317.
    assert isinstance(trace.get_tracer_provider(), ProxyTracerProvider)
