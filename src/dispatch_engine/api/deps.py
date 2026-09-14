"""FastAPI dependencies. State is attached to the app so tests get a fresh instance each time."""

from typing import Annotated

from fastapi import Depends, Request

from dispatch_engine.domain import DispatchEngine
from dispatch_engine.infra.memory import InMemoryRepository


def get_repository(request: Request) -> InMemoryRepository:
    return request.app.state.repository


def get_engine(request: Request) -> DispatchEngine:
    return request.app.state.engine


Repository = Annotated[InMemoryRepository, Depends(get_repository)]
Engine = Annotated[DispatchEngine, Depends(get_engine)]
