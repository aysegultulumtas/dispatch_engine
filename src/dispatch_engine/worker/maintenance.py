"""Hourly maintenance sweep, run inside the worker through RQ's own scheduler.

Rules are fixed on purpose (no configuration to get wrong):
- finished (succeeded/failed) runs older than 30 days are deleted
- idempotency keys older than 24 hours are deleted
- a run `running` for more than 15 minutes is failed ("stale: worker lost")
- a run `queued` for more than 5 minutes whose RQ job is gone (or already
  finished without ever starting the run) is re-enqueued under the same id

Scheduling: schedule_sweeps() enqueues one sweep at worker start with an RQ
Repeat; after each sweep the worker re-schedules the next one an hour later, and
its scheduler process (work(with_scheduler=True)) pushes it back onto the queue
when due. The fixed job id means a worker restart overwrites the pending sweep
instead of stacking up parallel chains.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus
from rq.repeat import Repeat

from dispatch_engine.domain import DispatchRunStatus
from dispatch_engine.infra.idempotency import KEY_TTL, PostgresIdempotencyStore
from dispatch_engine.infra.postgres import PostgresRepository
from dispatch_engine.infra.queue import dispatch_queue

from .tasks import enqueue_dispatch, worker_sessions

log = structlog.get_logger(__name__)

SWEEP_JOB_ID = "maintenance-sweep"
SWEEP_INTERVAL = timedelta(hours=1)
FINISHED_RUN_RETENTION = timedelta(days=30)
RUNNING_TIMEOUT = timedelta(minutes=15)
QUEUED_TIMEOUT = timedelta(minutes=5)
_RQ_DONE = (JobStatus.FINISHED, JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED)


def schedule_sweeps(queue: Queue) -> None:
    """Once at worker start: sweep now, then every hour (RQ Repeat needs a finite count)."""
    queue.enqueue(
        run_sweep,
        job_id=SWEEP_JOB_ID,
        repeat=Repeat(times=10**6, interval=int(SWEEP_INTERVAL.total_seconds())),
    )


def run_sweep() -> None:
    asyncio.run(sweep(dispatch_queue))


async def sweep(queue: Queue) -> dict[str, int]:
    now = datetime.now(UTC)
    async with worker_sessions() as session_maker:
        async with session_maker() as session:
            repo = PostgresRepository(session)
            deleted = await repo.delete_finished_dispatch_runs(now - FINISHED_RUN_RETENTION)

            stale = await repo.list_stale_dispatch_runs(
                DispatchRunStatus.RUNNING, now - RUNNING_TIMEOUT
            )
            for run in stale:
                run.fail("stale: worker lost")
                await repo.update_dispatch_run(run)

            requeued = 0
            for run in await repo.list_stale_dispatch_runs(
                DispatchRunStatus.QUEUED, now - QUEUED_TIMEOUT
            ):
                if _rq_job_is_gone(queue, run.id):
                    enqueue_dispatch(queue, run.id)
                    requeued += 1

        purged = await PostgresIdempotencyStore(session_maker).purge_expired(now - KEY_TTL)

    counts = {
        "deleted_runs": deleted,
        "failed_stale_runs": len(stale),
        "requeued_runs": requeued,
        "purged_keys": purged,
    }
    log.info("maintenance sweep", **counts)
    return counts


def _rq_job_is_gone(queue: Queue, run_id: UUID) -> bool:
    try:
        job = Job.fetch(str(run_id), connection=queue.connection)
    except NoSuchJobError:
        return True
    return job.get_status() in _RQ_DONE
