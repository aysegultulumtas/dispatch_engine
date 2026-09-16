"""Maintenance sweep against a real Postgres + Redis (docker compose up -d
postgres redis). Same skip/CI policy as test_worker.py, same disposable
dispatch_test database, and a private RQ queue so a worker on the shared
"dispatch" queue can't consume the jobs this test inspects."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dispatch_engine.domain import DispatchRun, DispatchRunStatus
from dispatch_engine.infra.db import Base
from dispatch_engine.infra.idempotency import PostgresIdempotencyStore
from dispatch_engine.infra.orm import DispatchRunRow, IdempotencyKeyRow
from dispatch_engine.infra.postgres import PostgresRepository
from dispatch_engine.infra.queue import REDIS_URL
from dispatch_engine.worker.maintenance import sweep
from dispatch_engine.worker.tasks import enqueue_dispatch

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://dispatch:dispatch@localhost:5432/dispatch_test"
)
IN_CI = bool(os.environ.get("CI"))


def _unreachable(reason: str) -> None:
    if IN_CI:
        pytest.fail(f"Postgres/Redis required in CI but unreachable: {reason}")
    pytest.skip(f"Postgres/Redis not reachable: {reason}")


def _age(ts: timedelta) -> datetime:
    return datetime.now(UTC) - ts


async def _seed(queue: Queue) -> dict[str, UUID]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except OSError as exc:
        await engine.dispose()
        _unreachable(str(exc))
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    ids: dict[str, UUID] = {}
    async with session_maker() as s:
        repo = PostgresRepository(s, actor="test")

        async def run(name: str, status: DispatchRunStatus, age: timedelta) -> None:
            r = await repo.add_dispatch_run(DispatchRun())
            if status is not DispatchRunStatus.QUEUED:
                r.start()
            if status is DispatchRunStatus.SUCCEEDED:
                r.succeed([])
            await repo.update_dispatch_run(r)
            await s.execute(
                update(DispatchRunRow)
                .where(DispatchRunRow.id == r.id)
                .values(created_at=_age(age), updated_at=_age(age))
            )
            await s.commit()
            ids[name] = r.id

        await run("old_finished", DispatchRunStatus.SUCCEEDED, timedelta(days=31))
        await run("recent_finished", DispatchRunStatus.SUCCEEDED, timedelta(days=1))
        await run("stale_running", DispatchRunStatus.RUNNING, timedelta(minutes=20))
        await run("fresh_running", DispatchRunStatus.RUNNING, timedelta(minutes=1))
        await run("orphan_queued", DispatchRunStatus.QUEUED, timedelta(minutes=6))
        await run("tracked_queued", DispatchRunStatus.QUEUED, timedelta(minutes=6))
        await run("fresh_queued", DispatchRunStatus.QUEUED, timedelta(seconds=10))
        enqueue_dispatch(queue, ids["tracked_queued"])  # RQ still has it: leave it alone

        store = PostgresIdempotencyStore(session_maker)
        await store.reserve("old-key", "h")
        await store.reserve("fresh-key", "h")
        await s.execute(
            update(IdempotencyKeyRow)
            .where(IdempotencyKeyRow.key == "old-key")
            .values(created_at=_age(timedelta(hours=25)))
        )
        await s.commit()
    await engine.dispose()
    return ids


async def _assert_and_drop(ids: dict[str, UUID], queue: Queue) -> None:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as s:
        repo = PostgresRepository(s, actor="test")

        async def status(name: str) -> DispatchRunStatus | None:
            r = await repo.get_dispatch_run(ids[name])
            return r.status if r else None

        assert await status("old_finished") is None  # > 30 days: deleted
        assert await status("recent_finished") is DispatchRunStatus.SUCCEEDED
        stale = await repo.get_dispatch_run(ids["stale_running"])
        assert stale is not None
        assert (stale.status, stale.error) == (DispatchRunStatus.FAILED, "stale: worker lost")
        assert await status("fresh_running") is DispatchRunStatus.RUNNING
        assert await status("orphan_queued") is DispatchRunStatus.QUEUED  # re-enqueued, not touched
        assert await status("tracked_queued") is DispatchRunStatus.QUEUED

        store = PostgresIdempotencyStore(session_maker)
        assert await store.reserve("old-key", "h") is None  # purged, so we could claim it again
        assert await store.reserve("fresh-key", "h") is not None

    # RQ side: the orphan got a job under its run id, the tracked one kept its single job,
    # the fresh one is still too young to be touched.
    assert Job.fetch(str(ids["orphan_queued"]), connection=queue.connection).is_queued
    assert Job.fetch(str(ids["tracked_queued"]), connection=queue.connection).is_queued
    with pytest.raises(NoSuchJobError):
        Job.fetch(str(ids["fresh_queued"]), connection=queue.connection)
    assert queue.count == 2

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def test_sweep_applies_every_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = redis.Redis.from_url(REDIS_URL)
    try:
        conn.ping()
    except redis.RedisError as exc:
        _unreachable(str(exc))
    monkeypatch.setattr("dispatch_engine.worker.tasks.DATABASE_URL", TEST_DATABASE_URL)
    queue = Queue("dispatch-test-sweep", connection=conn)
    queue.empty()  # type: ignore[no-untyped-call]

    ids = asyncio.run(_seed(queue))
    try:
        counts = asyncio.run(sweep(queue))
        assert counts == {
            "deleted_runs": 1,
            "failed_stale_runs": 1,
            "requeued_runs": 1,
            "purged_keys": 1,
        }
        asyncio.run(_assert_and_drop(ids, queue))
    finally:
        queue.empty()  # type: ignore[no-untyped-call]
