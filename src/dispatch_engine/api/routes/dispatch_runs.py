from uuid import UUID

import anyio
from fastapi import APIRouter, HTTPException, status
from rq import Retry

from dispatch_engine.domain import DispatchRun
from dispatch_engine.worker.tasks import run_dispatch

from ..deps import DispatchQueue, Repository
from ..schemas import DispatchRunRead

router = APIRouter(prefix="/dispatch-runs", tags=["dispatch"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_dispatch_run(repo: Repository, queue: DispatchQueue) -> DispatchRunRead:
    run = await repo.add_dispatch_run(DispatchRun())
    # queue.enqueue talks to Redis synchronously; run it off the event loop so a
    # slow/unavailable broker doesn't stall every other request being served.
    await anyio.to_thread.run_sync(
        lambda: queue.enqueue(
            run_dispatch,
            str(run.id),
            job_id=str(run.id),  # RQ job id == our run id: makes re-enqueue idempotent
            retry=Retry(max=2, interval=[10, 30]),
        )
    )
    return DispatchRunRead.from_domain(run)


@router.get("/{run_id}")
async def get_dispatch_run(run_id: UUID, repo: Repository) -> DispatchRunRead:
    run = await repo.get_dispatch_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dispatch run not found")
    return DispatchRunRead.from_domain(run)
