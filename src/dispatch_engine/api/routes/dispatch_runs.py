from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import anyio
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from dispatch_engine.domain import DispatchRun, DispatchRunStatus
from dispatch_engine.infra.repository import Repository as RepositoryProtocol
from dispatch_engine.worker.tasks import enqueue_dispatch

from ..deps import DispatchQueue, Repository
from ..schemas import DispatchRunRead

router = APIRouter(prefix="/dispatch-runs", tags=["dispatch"])

EVENT_POLL_INTERVAL = 1.0  # seconds between status checks while streaming
EVENT_STREAM_TIMEOUT = timedelta(minutes=10)  # a client never holds a connection longer
_TERMINAL = (DispatchRunStatus.SUCCEEDED, DispatchRunStatus.FAILED)


async def _run_or_404(repo: RepositoryProtocol, run_id: UUID) -> DispatchRun:
    run = await repo.get_dispatch_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dispatch run not found")
    return run


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_dispatch_run(repo: Repository, queue: DispatchQueue) -> DispatchRunRead:
    run = await repo.add_dispatch_run(DispatchRun())
    # enqueue talks to Redis synchronously; run it off the event loop so a
    # slow/unavailable broker doesn't stall every other request being served.
    await anyio.to_thread.run_sync(enqueue_dispatch, queue, run.id)
    return DispatchRunRead.from_domain(run)


@router.get("/{run_id}")
async def get_dispatch_run(run_id: UUID, repo: Repository) -> DispatchRunRead:
    return DispatchRunRead.from_domain(await _run_or_404(repo, run_id))


@router.get("/{run_id}/events", response_class=StreamingResponse)
async def stream_dispatch_run(run_id: UUID, repo: Repository) -> StreamingResponse:
    """Server-Sent Events: the current state, then one event per status change;
    closes after a terminal status. Same JSON as GET /dispatch-runs/{id}, which
    stays available for plain polling."""
    run = await _run_or_404(repo, run_id)
    return StreamingResponse(
        _events(repo, run), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


async def _events(repo: RepositoryProtocol, run: DispatchRun) -> AsyncIterator[str]:
    # One request-scoped session polls the database; FastAPI keeps yield
    # dependencies open until the streamed response has finished.
    deadline = anyio.current_time() + EVENT_STREAM_TIMEOUT.total_seconds()
    last: DispatchRunStatus | None = None
    while True:
        if run.status is not last:
            yield f"data: {DispatchRunRead.from_domain(run).model_dump_json()}\n\n"
            last = run.status
        if run.status in _TERMINAL or anyio.current_time() >= deadline:
            return
        await anyio.sleep(EVENT_POLL_INTERVAL)
        current = await repo.get_dispatch_run(run.id)
        if current is None:  # swept away mid-stream; nothing more will happen
            return
        run = current
