"""Dict-backed store. Async to match the Repository protocol (see repository.py);
no real I/O happens here, the object already holds the current state in place."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from dispatch_engine.domain import DispatchRun, DispatchRunStatus, Job, Technician

from .repository import Keyset


class _HasKeyset(Protocol):
    @property
    def id(self) -> UUID: ...
    @property
    def created_at(self) -> datetime: ...


def _page[T: _HasKeyset](items: Iterable[T], limit: int | None, after: Keyset | None) -> list[T]:
    ordered = sorted(items, key=lambda x: (x.created_at, x.id))
    if after is not None:
        ordered = [x for x in ordered if (x.created_at, x.id) > after]
    return ordered if limit is None else ordered[:limit]


class InMemoryRepository:
    def __init__(self) -> None:
        self._technicians: dict[UUID, Technician] = {}
        self._jobs: dict[UUID, Job] = {}
        self._dispatch_runs: dict[UUID, DispatchRun] = {}
        self._run_updated_at: dict[UUID, datetime] = {}  # mirrors the updated_at column

    async def add_technician(self, technician: Technician) -> Technician:
        self._technicians[technician.id] = technician
        return technician

    async def get_technician(self, technician_id: UUID) -> Technician | None:
        return self._technicians.get(technician_id)

    async def list_technicians(
        self, limit: int | None = None, after: Keyset | None = None
    ) -> list[Technician]:
        return _page(self._technicians.values(), limit, after)

    async def update_technician(self, technician: Technician) -> None:
        # already the same object; kept for interface parity
        self._technicians[technician.id] = technician

    async def add_job(self, job: Job) -> Job:
        self._jobs[job.id] = job
        return job

    async def get_job(self, job_id: UUID) -> Job | None:
        return self._jobs.get(job_id)

    async def list_jobs(self, limit: int | None = None, after: Keyset | None = None) -> list[Job]:
        return _page(self._jobs.values(), limit, after)

    async def update_job(self, job: Job) -> None:
        self._jobs[job.id] = job  # already the same object; kept for interface parity

    async def add_dispatch_run(self, run: DispatchRun) -> DispatchRun:
        self._dispatch_runs[run.id] = run
        self._run_updated_at[run.id] = run.created_at
        return run

    async def get_dispatch_run(self, run_id: UUID) -> DispatchRun | None:
        return self._dispatch_runs.get(run_id)

    async def update_dispatch_run(self, run: DispatchRun) -> None:
        self._dispatch_runs[run.id] = run  # already the same object; kept for interface parity
        self._run_updated_at[run.id] = datetime.now(UTC)

    async def list_stale_dispatch_runs(
        self, status: DispatchRunStatus, not_updated_since: datetime
    ) -> list[DispatchRun]:
        return [
            run
            for run in self._dispatch_runs.values()
            if run.status is status and self._run_updated_at[run.id] < not_updated_since
        ]

    async def delete_finished_dispatch_runs(self, before: datetime) -> int:
        finished = (DispatchRunStatus.SUCCEEDED, DispatchRunStatus.FAILED)
        stale = [
            run.id
            for run in self._dispatch_runs.values()
            if run.status in finished and self._run_updated_at[run.id] < before
        ]
        for run_id in stale:
            del self._dispatch_runs[run_id]
            del self._run_updated_at[run_id]
        return len(stale)
