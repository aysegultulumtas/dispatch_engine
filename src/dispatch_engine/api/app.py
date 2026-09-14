"""Application factory. Wires domain + infra into HTTP; no business logic here."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from dispatch_engine import __version__
from dispatch_engine.domain import DispatchEngine, DomainError

from .routes import jobs, technicians


def create_app() -> FastAPI:
    app = FastAPI(title="Dispatch Engine", version=__version__)
    app.state.engine = DispatchEngine()
    app.include_router(technicians.router)
    app.include_router(jobs.router)

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        # Rule violations conflict with current state (409); client typos are 422.
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
