"""PostgreSQL-backed repository. Converts between domain dataclasses and ORM rows;
domain objects never touch SQLAlchemy directly."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from dispatch_engine.domain import Job, JobStatus, Technician

from .orm import JobRow, TechnicianRow


def _technician_to_domain(row: TechnicianRow) -> Technician:
    return Technician(
        id=row.id,
        name=row.name,
        max_jobs=row.max_jobs,
        skills=frozenset(row.skills),
        job_ids=[j.id for j in row.jobs if j.status != JobStatus.COMPLETED],
    )


def _job_to_domain(row: JobRow) -> Job:
    return Job(
        id=row.id,
        title=row.title,
        skill=row.skill,
        status=JobStatus(row.status),
        technician_id=row.technician_id,
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

    async def list_technicians(self) -> list[Technician]:
        stmt = select(TechnicianRow).options(selectinload(TechnicianRow.jobs))
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
        )
        self._session.add(row)
        await self._session.commit()
        return job

    async def get_job(self, job_id: UUID) -> Job | None:
        row = await self._session.get(JobRow, job_id)
        return _job_to_domain(row) if row else None

    async def list_jobs(self) -> list[Job]:
        rows = (await self._session.execute(select(JobRow))).scalars().all()
        return [_job_to_domain(row) for row in rows]

    async def update_job(self, job: Job) -> None:
        row = await self._session.get(JobRow, job.id)
        if row is None:
            raise ValueError(f"job {job.id} not found")
        row.status = job.status.value
        row.technician_id = job.technician_id
        await self._session.commit()
