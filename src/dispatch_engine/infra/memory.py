"""Dict-backed store. Replaced by a PostgreSQL repository in a later phase."""

from uuid import UUID

from dispatch_engine.domain import Job, Technician


class InMemoryRepository:
    def __init__(self) -> None:
        self._technicians: dict[UUID, Technician] = {}
        self._jobs: dict[UUID, Job] = {}

    def add_technician(self, technician: Technician) -> Technician:
        self._technicians[technician.id] = technician
        return technician

    def get_technician(self, technician_id: UUID) -> Technician | None:
        return self._technicians.get(technician_id)

    def list_technicians(self) -> list[Technician]:
        return list(self._technicians.values())

    def add_job(self, job: Job) -> Job:
        self._jobs[job.id] = job
        return job

    def get_job(self, job_id: UUID) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        return list(self._jobs.values())
