"""Structured logging, request/run correlation, optional OpenTelemetry tracing.

- structlog renders to a console on a TTY and to JSON otherwise (no switch);
  uvicorn, rq and everything else on the stdlib root logger share the renderer.
- RequestIdMiddleware reads or generates X-Request-ID, binds it to a contextvar so
  every log line inside the request carries it, and echoes it on the response.
  The worker binds run_id the same way (see worker/tasks.py).
- Tracing exists only when the standard OTEL_EXPORTER_OTLP_ENDPOINT is set. Without
  it no TracerProvider is installed, so nothing is exported and nothing complains
  about an unreachable localhost:4317. When on, trace_id joins every log line.
"""

import logging
import os
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_ID_HEADER = "X-Request-ID"

log = structlog.get_logger(__name__)
_logging_configured = False


def _add_trace_id(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
    return event_dict


def configure_logging() -> None:
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True

    renderer: Any = (
        structlog.dev.ConsoleRenderer()
        if sys.stderr.isatty()
        else structlog.processors.JSONRenderer()
    )
    pre_chain: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_trace_id,
    ]
    structlog.configure(
        processors=[*pre_chain, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=pre_chain,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # uvicorn and rq install their own handlers with propagate=False; fold them in.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "rq.worker", "rq.scheduler"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    # RequestIdMiddleware logs each request with its request_id; uvicorn's own
    # access line would be the same information without the correlation.
    logging.getLogger("uvicorn.access").disabled = True


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        log.info(
            "request", method=request.method, path=request.url.path, status=response.status_code
        )
        return response


def configure_tracing(app: FastAPI | None = None, engine: AsyncEngine | None = None) -> None:
    """Install OTLP tracing if — and only if — OTEL_EXPORTER_OTLP_ENDPOINT is set.

    Service name and the endpoint come from the standard OTEL_* variables; this
    project adds no knobs of its own. Pass the API's engine so its already-created
    pool is instrumented; the worker creates engines later, so it passes none and
    the instrumentor patches create_async_engine instead.
    """
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    RedisInstrumentor().instrument()
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    else:
        SQLAlchemyInstrumentor().instrument()
    if app is not None:
        FastAPIInstrumentor.instrument_app(app)
