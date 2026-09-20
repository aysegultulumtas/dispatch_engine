"""Application factory. Wires domain + infra into HTTP; no business logic here."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from dispatch_engine import __version__
from dispatch_engine.domain import DispatchEngine, DomainError
from dispatch_engine.infra.db import async_session_maker
from dispatch_engine.infra.db import engine as db_engine
from dispatch_engine.infra.idempotency import PostgresIdempotencyStore
from dispatch_engine.infra.queue import REDIS_URL
from dispatch_engine.infra.ratelimit import RedisTokenBucket
from dispatch_engine.observability import RequestIdMiddleware, configure_logging, configure_tracing

from .idempotency import IdempotencyMiddleware
from .ratelimit import rate_limit
from .routes import dispatch_runs, jobs, technicians
from .security import expected_api_key, require_api_key

# Local frontend dev servers only (Vite default 5173, Lovable-exported apps default 8080).
# Tighten this to a real deployed origin before this ever leaves localhost.
LOCAL_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:8080",
    "http://localhost:3000",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await db_engine.dispose()
    await app.state.rate_limiter.aclose()


def create_app() -> FastAPI:
    if expected_api_key() is None:
        # Fail at boot, not at the first request: an API with no key configured
        # would otherwise be wide open (or, with a default, have a known secret).
        raise RuntimeError("API_KEY environment variable is required")

    configure_logging()
    app = FastAPI(title="Dispatch Engine", version=__version__, lifespan=lifespan)
    configure_tracing(app, db_engine)

    # Middleware order: the last one added runs first (outermost). Request-ID wraps
    # everything so even a CORS preflight or an idempotent replay is correlated.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=LOCAL_DEV_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Next-Cursor", "Retry-After"],
    )
    app.add_middleware(RequestIdMiddleware)

    app.state.engine = DispatchEngine()
    app.state.idempotency_store = PostgresIdempotencyStore(async_session_maker)
    app.state.rate_limiter = RedisTokenBucket(Redis.from_url(REDIS_URL))

    # Everything that touches data lives under /v1, needs the key and is rate
    # limited (in that order). /health, /ready and the docs stay open at the root.
    v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key), Depends(rate_limit)])
    v1.include_router(technicians.router)
    v1.include_router(jobs.router)
    v1.include_router(dispatch_runs.router)
    app.include_router(v1)

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        # Rule violations conflict with current state (409); client typos are 422.
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        # Liveness: the process is up. Deliberately checks no dependencies, so a
        # database outage does not get this container restarted in a loop.
        return {"status": "ok", "version": __version__}

    @app.get("/ready", tags=["system"])
    async def ready() -> JSONResponse:
        # Readiness: can we actually serve? Any connection failure (refused, auth,
        # timeout) means "not yet"; the orchestrator decides what to do with that.
        problems: dict[str, str] = {}
        try:
            async with db_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            problems["database"] = str(exc)

        redis = Redis.from_url(REDIS_URL)
        try:
            await redis.ping()
        except Exception as exc:  # noqa: BLE001
            problems["redis"] = str(exc)
        finally:
            await redis.aclose()

        if problems:
            return JSONResponse(status_code=503, content={"status": "unavailable", **problems})
        return JSONResponse(content={"status": "ready"})

    return app


# No module-level `app = create_app()`: the factory reads API_KEY and must fail at
# process start, not on import. Run with `uvicorn dispatch_engine.api.app:create_app --factory`.
