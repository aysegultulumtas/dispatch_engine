"""RQ task: runs a queued DispatchRun to completion.

Runs in the worker process (see docker-compose.yml's `worker` service), never in
the API's event loop — see api/routes/jobs.py's dispatch_job for why a real
solver (Faz 9) cannot run inline. asyncio.run() gives each invocation its own
event loop, so worker_sessions() owns a private engine via NullPool rather than
reusing api's module-level engine (infra/db.py) — an asyncpg connection pool
tied to a dead event loop breaks the next call (same reasoning as
tests/test_postgres_repository.py's session fixture).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import structlog
from rq import Queue, Retry, get_current_job
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dispatch_engine.domain import DispatchEngine, DispatchRunStatus, JobStatus
from dispatch_engine.infra.db import DATABASE_URL
from dispatch_engine.infra.postgres import PostgresRepository

log = structlog.get_logger(__name__)

# Raised by a broken connection, not by a bad job. Retried by RQ (see enqueue_dispatch);
# anything else is a logic error and retrying it would just repeat it.
_RETRYABLE = (OSError, ConnectionError, TimeoutError)


def enqueue_dispatch(queue: Queue, run_id: UUID) -> None:
    """RQ job id == our run id: re-enqueueing the same run (API retry, maintenance
    sweep) overwrites rather than duplicates, and run_dispatch is a no-op once the
    run is terminal."""
    queue.enqueue(
        run_dispatch, str(run_id), job_id=str(run_id), retry=Retry(max=2, interval=[10, 30])
    )


@asynccontextmanager
async def worker_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory on a private NullPool engine, disposed when the task ends."""
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def run_dispatch(run_id: str) -> None:
    structlog.contextvars.bind_contextvars(run_id=run_id)
    try:
        asyncio.run(_run_dispatch(run_id))
    finally:
        structlog.contextvars.unbind_contextvars("run_id")


async def _run_dispatch(run_id: str) -> None:
    async with worker_sessions() as session_maker, session_maker() as session:
        repo = PostgresRepository(session, actor=f"worker:{run_id}")
        run = await repo.get_dispatch_run(UUID(run_id))
        if run is None or run.status in (DispatchRunStatus.SUCCEEDED, DispatchRunStatus.FAILED):
            log.info("dispatch run skipped", reason="unknown or already finished")
            return  # idempotent: unknown run, or already terminal — nothing to do

        run.start()
        await repo.update_dispatch_run(run)

        try:
            pending = [j for j in await repo.list_jobs() if j.status is JobStatus.PENDING]
            technicians = {t.id: t for t in await repo.list_technicians()}
            assignments = DispatchEngine().dispatch_all(pending, technicians.values())

            for job in pending:
                if job.status is not JobStatus.PENDING:  # got assigned
                    await repo.update_job(job)
            for technician_id in {a.technician_id for a in assignments}:
                await repo.update_technician(technicians[technician_id])

            run.succeed(assignments)
            await repo.update_dispatch_run(run)
            log.info("dispatch run succeeded", pending=len(pending), assigned=len(assignments))
        except Exception as exc:
            run.fail(str(exc))
            await repo.update_dispatch_run(run)
            retryable = isinstance(exc, _RETRYABLE)
            log.exception("dispatch run failed", retryable=retryable)
            if not retryable:
                rq_job = get_current_job()
                if rq_job is not None:
                    rq_job.retries_left = 0
            raise
