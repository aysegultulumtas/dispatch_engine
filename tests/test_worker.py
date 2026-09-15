"""Integration test for the RQ task against a real Postgres + Redis (docker
compose up -d postgres redis). Skipped automatically if either is unreachable
— except in CI (CI=true), where that's a broken pipeline, not a reason to
report green (same policy as test_postgres_repository.py).

run_dispatch() does its own asyncio.run() internally (it's written to be
called from a sync RQ worker process), so this test cannot itself be an
`async def` — asyncio.run() cannot start inside an already-running event
loop. Everything async here is a standalone coroutine run via its own
asyncio.run() call instead of an async test + fixture."""

import asyncio
import os
from uuid import UUID

import pytest
import redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dispatch_engine.domain import (
    Assignment,
    DispatchRun,
    DispatchRunStatus,
    Job,
    JobStatus,
    Technician,
)
from dispatch_engine.infra.db import Base
from dispatch_engine.infra.postgres import PostgresRepository
from dispatch_engine.infra.queue import REDIS_URL
from dispatch_engine.worker.tasks import run_dispatch

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://dispatch:dispatch@localhost:5432/dispatch_test"
)
IN_CI = bool(os.environ.get("CI"))


def _unreachable(reason: str) -> None:
    if IN_CI:
        pytest.fail(f"Postgres/Redis required in CI but unreachable: {reason}")
    pytest.skip(f"Postgres/Redis not reachable: {reason}")


async def _seed() -> tuple[UUID, UUID, UUID]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except OSError as exc:
        await engine.dispose()
        _unreachable(str(exc))
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as s:
        repo = PostgresRepository(s)
        tech = await repo.add_technician(
            Technician(name="Ada", max_jobs=1, skills=frozenset({"hvac"}))
        )
        job = await repo.add_job(Job(title="Fix AC", skill="hvac"))
        run = await repo.add_dispatch_run(DispatchRun())
    await engine.dispose()
    return tech.id, job.id, run.id


async def _assert_and_drop(job_id: UUID, tech_id: UUID, run_id: UUID) -> None:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as s:
        repo = PostgresRepository(s)
        run = await repo.get_dispatch_run(run_id)
        assert run is not None
        assert run.status is DispatchRunStatus.SUCCEEDED
        assert run.assignments == [Assignment(job_id=job_id, technician_id=tech_id)]
        job = await repo.get_job(job_id)
        assert job is not None
        assert job.status is JobStatus.ASSIGNED
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def test_worker_runs_dispatch_run_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        redis.Redis.from_url(REDIS_URL).ping()
    except redis.RedisError as exc:
        _unreachable(str(exc))

    # The task reads DATABASE_URL from its own module (bound at import time),
    # not the environment directly — point it at the disposable test DB,
    # never the dev one (see docker/init-test-db.sql and Faz 4's history).
    monkeypatch.setattr("dispatch_engine.worker.tasks.DATABASE_URL", TEST_DATABASE_URL)

    tech_id, job_id, run_id = asyncio.run(_seed())

    run_dispatch(str(run_id))
    run_dispatch(str(run_id))  # idempotency: no-op, must not double-assign or error

    asyncio.run(_assert_and_drop(job_id, tech_id, run_id))
