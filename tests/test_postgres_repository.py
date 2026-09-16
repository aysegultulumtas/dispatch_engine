"""Integration tests against a real Postgres (docker compose up -d postgres).
Skipped automatically if the DB is unreachable — except in CI (CI=true), where a
missing database is a broken pipeline, not a reason to report green.

Runs against a dedicated "dispatch_test" database (created by
docker/init-test-db.sql), never the dev "dispatch" DB — create_all/drop_all here
must not touch data a developer is poking at through the running app."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dispatch_engine.api.app import create_app
from dispatch_engine.domain import Job, JobStatus, Technician
from dispatch_engine.infra.db import Base
from dispatch_engine.infra.idempotency import PostgresIdempotencyStore
from dispatch_engine.infra.postgres import PostgresRepository

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://dispatch:dispatch@localhost:5432/dispatch_test"
)
IN_CI = bool(os.environ.get("CI"))


def _unreachable(reason: str) -> None:
    if IN_CI:
        pytest.fail(f"Postgres required in CI but unreachable: {reason}")
    pytest.skip(f"Postgres not reachable: {reason}")


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
        _unreachable(str(exc))

    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_maker() as s:
        yield s

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


async def test_add_and_get_technician(session: AsyncSession) -> None:
    repo = PostgresRepository(session, actor="test")
    tech = Technician(name="Ahmet", max_jobs=2, skills=frozenset({"elektrik"}))
    await repo.add_technician(tech)

    fetched = await repo.get_technician(tech.id)

    assert fetched is not None
    assert fetched.name == "Ahmet"
    assert fetched.skills == frozenset({"elektrik"})
    assert fetched.job_ids == []


async def test_one_to_many_job_assignment_persists(session: AsyncSession) -> None:
    repo = PostgresRepository(session, actor="test")
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
    repo = PostgresRepository(session, actor="test")
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


async def test_list_returns_everything_added(session: AsyncSession) -> None:
    repo = PostgresRepository(session, actor="test")
    t1 = await repo.add_technician(Technician(name="A", max_jobs=1, skills=frozenset({"x"})))
    t2 = await repo.add_technician(Technician(name="B", max_jobs=1, skills=frozenset({"y"})))
    j1 = await repo.add_job(Job(title="J1", skill="x"))
    j2 = await repo.add_job(Job(title="J2", skill="y"))

    assert {t.id for t in await repo.list_technicians()} == {t1.id, t2.id}
    assert {j.id for j in await repo.list_jobs()} == {j1.id, j2.id}


def test_ready_endpoint_reports_database_and_redis_reachable() -> None:
    # Goes through the app's own engine/redis connection (DATABASE_URL, REDIS_URL),
    # the same path the container healthcheck uses.
    with TestClient(create_app()) as client:
        r = client.get("/ready")
    if r.status_code == 503:
        _unreachable(str(r.json()))
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


async def test_idempotency_reservation_is_first_writer_wins(session: AsyncSession) -> None:
    # Same table, own transactions: the store gets a session maker, not the test session.
    store = PostgresIdempotencyStore(async_sessionmaker(session.bind, expire_on_commit=False))

    assert await store.reserve("k", "h1") is None
    taken = await store.reserve("k", "h1")  # second INSERT hits the PK → IntegrityError path
    assert taken is not None
    assert taken.status_code is None  # still "in progress"

    await store.complete("k", 201, {"id": "x"})
    replay = await store.reserve("k", "h1")
    assert replay is not None
    assert (replay.status_code, replay.response_body) == (201, {"id": "x"})

    await store.release("k")
    assert await store.reserve("k", "h2") is None
    assert await store.purge_expired(datetime.now(UTC) + timedelta(seconds=1)) == 1


async def test_keyset_pagination_orders_by_created_at_then_id(session: AsyncSession) -> None:
    repo = PostgresRepository(session, actor="test")
    jobs = [await repo.add_job(Job(title=f"J{i}", skill="x")) for i in range(3)]
    expected = [j.id for j in sorted(jobs, key=lambda j: (j.created_at, j.id))]

    first = await repo.list_jobs(limit=2)
    rest = await repo.list_jobs(limit=2, after=(first[-1].created_at, first[-1].id))

    assert [j.id for j in first] == expected[:2]
    assert [j.id for j in rest] == expected[2:]  # the row-value comparison resumes past the cursor


async def test_update_job_appends_an_event_only_on_status_change(session: AsyncSession) -> None:
    repo = PostgresRepository(session, actor="api")
    tech = await repo.add_technician(Technician(name="Ada", max_jobs=1, skills=frozenset({"x"})))
    job = await repo.add_job(Job(title="J", skill="x"))

    await repo.update_job(job)  # no transition → no row
    tech.take(job)
    await repo.update_job(job)
    tech.release(job)
    await repo.update_job(job)

    events = await repo.list_job_events(job.id)
    assert [(e.from_status, e.to_status, e.technician_id, e.actor) for e in events] == [
        (JobStatus.PENDING, JobStatus.ASSIGNED, tech.id, "api"),
        (JobStatus.ASSIGNED, JobStatus.COMPLETED, tech.id, "api"),
    ]
