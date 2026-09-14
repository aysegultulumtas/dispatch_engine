"""Dict-backed store. Async to match the Repository protocol (see repository.py);
no real I/O happens here, the object already holds the current state in place."""

from uuid import UUID

from dispatch_engine.domain import Job, Technician


class InMemoryRepository:
    def __init__(self) -> None:
        self._technicians: dict[UUID, Technician] = {}
        self._jobs: dict[UUID, Job] = {}

    async def add_technician(self, technician: Technician) -> Technician:
        self._technicians[technician.id] = technician
        return technician

    async def get_technician(self, technician_id: UUID) -> Technician | None:
        return self._technicians.get(technician_id)

    async def list_technicians(self) -> list[Technician]:
        return list(self._technicians.values())

    async def update_technician(self, technician: Technician) -> None:
        # already the same object; kept for interface parity
        self._technicians[technician.id] = technician

    async def add_job(self, job: Job) -> Job:
        self._jobs[job.id] = job
        return job

    async def get_job(self, job_id: UUID) -> Job | None:
        return self._jobs.get(job_id)

    async def list_jobs(self) -> list[Job]:
        return list(self._jobs.values())

    async def update_job(self, job: Job) -> None:
        self._jobs[job.id] = job  # already the same object; kept for interface parity
