"""FastAPI dependencies. get_repository defaults to Postgres; tests override it
with an in-memory repository via app.dependency_overrides (see tests/conftest.py)."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from rq import Queue
from sqlalchemy.ext.asyncio import AsyncSession

from dispatch_engine.domain import DispatchEngine
from dispatch_engine.infra.db import async_session_maker
from dispatch_engine.infra.postgres import PostgresRepository
from dispatch_engine.infra.queue import dispatch_queue
from dispatch_engine.infra.repository import Repository as RepositoryProtocol


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session


def get_repository(session: Annotated[AsyncSession, Depends(get_db_session)]) -> RepositoryProtocol:
    return PostgresRepository(session)


def get_engine(request: Request) -> DispatchEngine:
    engine: DispatchEngine = request.app.state.engine
    return engine


def get_queue() -> Queue:
    return dispatch_queue


Repository = Annotated[RepositoryProtocol, Depends(get_repository)]
Engine = Annotated[DispatchEngine, Depends(get_engine)]
DispatchQueue = Annotated[Queue, Depends(get_queue)]
