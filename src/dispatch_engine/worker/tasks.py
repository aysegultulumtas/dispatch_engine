"""RQ task: runs a queued DispatchRun to completion.

Runs in the worker process (see docker-compose.yml's `worker` service), never in
the API's event loop — see api/routes/jobs.py's dispatch_job for why a real
solver (Faz 8) cannot run inline. asyncio.run() gives each invocation its own
event loop, so this owns a private engine via NullPool rather than reusing
api's module-level engine (infra/db.py) — an asyncpg connection pool tied to a
dead event loop breaks the next call (same reasoning as
tests/test_postgres_repository.py's session fixture).
"""

import asyncio
from uuid import UUID

from rq import get_current_job
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dispatch_engine.domain import DispatchEngine, DispatchRunStatus, JobStatus
from dispatch_engine.infra.db import DATABASE_URL
from dispatch_engine.infra.postgres import PostgresRepository

# Raised by a broken connection, not by a bad job. Retried by RQ (see infra/queue.py
# callers); anything else is a logic error and retrying it would just repeat it.
_RETRYABLE = (OSError, ConnectionError, TimeoutError)


def run_dispatch(run_id: str) -> None:
    asyncio.run(_run_dispatch(run_id))


async def _run_dispatch(run_id: str) -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as session:
            repo = PostgresRepository(session)
            run = await repo.get_dispatch_run(UUID(run_id))
            if run is None or run.status in (
                DispatchRunStatus.SUCCEEDED,
                DispatchRunStatus.FAILED,
            ):
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
            except Exception as exc:
                run.fail(str(exc))
                await repo.update_dispatch_run(run)
                if not isinstance(exc, _RETRYABLE):
                    rq_job = get_current_job()
                    if rq_job is not None:
                        rq_job.retries_left = 0
                raise
    finally:
        await engine.dispose()
