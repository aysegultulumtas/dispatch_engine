"""FastAPI dependencies. get_repository defaults to Postgres; tests override it
with an in-memory repository via app.dependency_overrides (see tests/conftest.py)."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from dispatch_engine.domain import DispatchEngine
from dispatch_engine.infra.db import async_session_maker
from dispatch_engine.infra.postgres import PostgresRepository
from dispatch_engine.infra.repository import Repository as RepositoryProtocol


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session


def get_repository(session: Annotated[AsyncSession, Depends(get_db_session)]) -> RepositoryProtocol:
    return PostgresRepository(session)


def get_engine(request: Request) -> DispatchEngine:
    return request.app.state.engine


Repository = Annotated[RepositoryProtocol, Depends(get_repository)]
Engine = Annotated[DispatchEngine, Depends(get_engine)]
