"""Integration tests against a real Postgres (docker compose up -d postgres).
Not part of the fast unit suite; skipped automatically if the DB is unreachable.

Runs against a dedicated "dispatch_test" database (created by
docker/init-test-db.sql), never the dev "dispatch" DB — create_all/drop_all here
must not touch data a developer is poking at through the running app."""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dispatch_engine.domain import Job, JobStatus, Technician
from dispatch_engine.infra.db import Base
from dispatch_engine.infra.postgres import PostgresRepository

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://dispatch:dispatch@localhost:5432/dispatch_test"
)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    # NullPool: a fresh connection per checkout, never reused across pytest-asyncio's
    # per-test event loops (a pooled connection tied to a dead loop breaks asyncpg).
    test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except OSError as exc:
        await test_engine.dispose()
        pytest.skip(f"Postgres not reachable: {exc}")

    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_maker() as s:
        yield s

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


async def test_add_and_get_technician(session: AsyncSession) -> None:
    repo = PostgresRepository(session)
    tech = Technician(name="Ahmet", max_jobs=2, skills=frozenset({"elektrik"}))
    await repo.add_technician(tech)

    fetched = await repo.get_technician(tech.id)

    assert fetched is not None
    assert fetched.name == "Ahmet"
    assert fetched.skills == frozenset({"elektrik"})
    assert fetched.job_ids == []


async def test_one_to_many_job_assignment_persists(session: AsyncSession) -> None:
    repo = PostgresRepository(session)
    tech_in = Technician(name="Ayşe", max_jobs=3, skills=frozenset({"tesisat"}))
    tech = await repo.add_technician(tech_in)
    job1 = await repo.add_job(Job(title="Musluk tamiri", skill="tesisat"))
    job2 = await repo.add_job(Job(title="Boru değişimi", skill="tesisat"))

    tech.take(job1)
    tech.take(job2)
    await repo.update_job(job1)
    await repo.update_job(job2)
    await repo.update_technician(tech)

    reloaded = await repo.get_technician(tech.id)

    assert reloaded is not None
    assert set(reloaded.job_ids) == {job1.id, job2.id}
    assert reloaded.load == 2


async def test_completed_job_no_longer_counts_toward_load(session: AsyncSession) -> None:
    repo = PostgresRepository(session)
    tech_in = Technician(name="Mert", max_jobs=1, skills=frozenset({"boya"}))
    tech = await repo.add_technician(tech_in)
    job = await repo.add_job(Job(title="Duvar boyama", skill="boya"))

    tech.take(job)
    await repo.update_job(job)
    tech.release(job)
    await repo.update_job(job)
    await repo.update_technician(tech)

    reloaded = await repo.get_technician(tech.id)
    reloaded_job = await repo.get_job(job.id)

    assert reloaded is not None
    assert reloaded.load == 0
    assert reloaded_job is not None
    assert reloaded_job.status == JobStatus.COMPLETED
