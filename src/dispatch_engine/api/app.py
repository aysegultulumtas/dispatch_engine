"""Application factory. Wires domain + infra into HTTP; no business logic here."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from dispatch_engine import __version__
from dispatch_engine.domain import DispatchEngine, DomainError
from dispatch_engine.infra.db import engine as db_engine

from .routes import jobs, technicians

# Local frontend dev servers only (Vite default 5173, Lovable-exported apps default 8080).
# Tighten this to a real deployed origin before this ever leaves localhost.
LOCAL_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:8080",
    "http://localhost:3000",
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await db_engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Dispatch Engine", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=LOCAL_DEV_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.engine = DispatchEngine()
    app.include_router(technicians.router)
    app.include_router(jobs.router)

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
        try:
            async with db_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                status_code=503, content={"status": "unavailable", "detail": str(exc)}
            )
        return JSONResponse(content={"status": "ready"})

    return app


app = create_app()
