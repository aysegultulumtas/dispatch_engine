"""PostgreSQL-backed repository. Converts between domain dataclasses and ORM rows;
domain objects never touch SQLAlchemy directly."""

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from dispatch_engine.domain import (
    Assignment,
    DispatchRun,
    DispatchRunStatus,
    Job,
    JobStatus,
    Technician,
)

from .orm import DispatchRunRow, JobRow, TechnicianRow
from .repository import Keyset

_FINISHED = (DispatchRunStatus.SUCCEEDED.value, DispatchRunStatus.FAILED.value)


def _technician_to_domain(row: TechnicianRow) -> Technician:
    return Technician(
        id=row.id,
        name=row.name,
        max_jobs=row.max_jobs,
        skills=frozenset(row.skills),
        job_ids=[j.id for j in row.jobs if j.status != JobStatus.COMPLETED],
        created_at=row.created_at,
    )


def _job_to_domain(row: JobRow) -> Job:
    return Job(
        id=row.id,
        title=row.title,
        skill=row.skill,
        status=JobStatus(row.status),
        technician_id=row.technician_id,
        created_at=row.created_at,
    )


def _dispatch_run_to_domain(row: DispatchRunRow) -> DispatchRun:
    return DispatchRun(
        id=row.id,
        status=DispatchRunStatus(row.status),
        assignments=[
            Assignment(job_id=UUID(a["job_id"]), technician_id=UUID(a["technician_id"]))
            for a in row.assignments
        ],
        error=row.error,
        created_at=row.created_at,
    )


class PostgresRepository:
    """One repository per request, backed by one AsyncSession (see api/deps.py)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_technician(self, technician: Technician) -> Technician:
        row = TechnicianRow(
            id=technician.id,
            name=technician.name,
            max_jobs=technician.max_jobs,
            skills=list(technician.skills),
            created_at=technician.created_at,
        )
        self._session.add(row)
        await self._session.commit()
        return technician

    async def get_technician(self, technician_id: UUID) -> Technician | None:
        stmt = (
            select(TechnicianRow)
            .options(selectinload(TechnicianRow.jobs))  # avoid MissingGreenlet on lazy load
            .where(TechnicianRow.id == technician_id)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _technician_to_domain(row) if row else None

    async def list_technicians(
        self, limit: int | None = None, after: Keyset | None = None
    ) -> list[Technician]:
        stmt = (
            select(TechnicianRow)
            .options(selectinload(TechnicianRow.jobs))
            .order_by(TechnicianRow.created_at, TechnicianRow.id)
        )
        if after is not None:
            stmt = stmt.where(tuple_(TechnicianRow.created_at, TechnicianRow.id) > after)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_technician_to_domain(row) for row in rows]

    async def update_technician(self, technician: Technician) -> None:
        row = await self._session.get(TechnicianRow, technician.id)
        if row is None:
            raise ValueError(f"technician {technician.id} not found")
        row.name = technician.name
        row.max_jobs = technician.max_jobs
        row.skills = list(technician.skills)
        await self._session.commit()

    async def add_job(self, job: Job) -> Job:
        row = JobRow(
            id=job.id,
            title=job.title,
            skill=job.skill,
            status=job.status.value,
            technician_id=job.technician_id,
            created_at=job.created_at,
        )
        self._session.add(row)
        await self._session.commit()
        return job

    async def get_job(self, job_id: UUID) -> Job | None:
        row = await self._session.get(JobRow, job_id)
        return _job_to_domain(row) if row else None

    async def list_jobs(self, limit: int | None = None, after: Keyset | None = None) -> list[Job]:
        stmt = select(JobRow).order_by(JobRow.created_at, JobRow.id)
        if after is not None:
            stmt = stmt.where(tuple_(JobRow.created_at, JobRow.id) > after)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_job_to_domain(row) for row in rows]

    async def update_job(self, job: Job) -> None:
        row = await self._session.get(JobRow, job.id)
        if row is None:
            raise ValueError(f"job {job.id} not found")
        row.status = job.status.value
        row.technician_id = job.technician_id
        await self._session.commit()

    async def add_dispatch_run(self, run: DispatchRun) -> DispatchRun:
        row = DispatchRunRow(
            id=run.id,
            status=run.status.value,
            assignments=[],
            error=run.error,
            created_at=run.created_at,
        )
        self._session.add(row)
        await self._session.commit()
        return run

    async def get_dispatch_run(self, run_id: UUID) -> DispatchRun | None:
        # populate_existing: the SSE stream polls this on one long-lived session, and
        # the identity map would otherwise keep returning the first status it saw.
        row = await self._session.get(DispatchRunRow, run_id, populate_existing=True)
        return _dispatch_run_to_domain(row) if row else None

    async def update_dispatch_run(self, run: DispatchRun) -> None:
        row = await self._session.get(DispatchRunRow, run.id)
        if row is None:
            raise ValueError(f"dispatch run {run.id} not found")
        row.status = run.status.value
        row.assignments = [
            {"job_id": str(a.job_id), "technician_id": str(a.technician_id)}
            for a in run.assignments
        ]
        row.error = run.error
        await self._session.commit()

    async def list_stale_dispatch_runs(
        self, status: DispatchRunStatus, not_updated_since: datetime
    ) -> list[DispatchRun]:
        stmt = select(DispatchRunRow).where(
            DispatchRunRow.status == status.value, DispatchRunRow.updated_at < not_updated_since
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_dispatch_run_to_domain(row) for row in rows]

    async def delete_finished_dispatch_runs(self, before: datetime) -> int:
        result = await self._session.execute(
            delete(DispatchRunRow).where(
                DispatchRunRow.status.in_(_FINISHED), DispatchRunRow.updated_at < before
            )
        )
        await self._session.commit()
        return cast(CursorResult[Any], result).rowcount
