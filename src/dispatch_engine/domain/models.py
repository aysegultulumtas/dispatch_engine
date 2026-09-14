"""Core entities. Framework-free on purpose: no Pydantic, no ORM, only rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4

from .exceptions import CapacityExceeded, InvalidTransition, SkillMismatch


class JobStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    COMPLETED = "completed"


@dataclass
class Job:
    """A unit of field work. Lifecycle: pending -> assigned -> completed."""

    title: str
    skill: str
    id: UUID = field(default_factory=uuid4)
    status: JobStatus = JobStatus.PENDING
    technician_id: UUID | None = None

    def assign_to(self, technician_id: UUID) -> None:
        if self.status is not JobStatus.PENDING:
            raise InvalidTransition(f"job {self.id} is {self.status}, cannot assign")
        self.technician_id = technician_id
        self.status = JobStatus.ASSIGNED

    def complete(self) -> None:
        if self.status is not JobStatus.ASSIGNED:
            raise InvalidTransition(f"job {self.id} is {self.status}, cannot complete")
        self.status = JobStatus.COMPLETED


@dataclass
class Technician:
    """A worker with a skill set and a hard cap on concurrent jobs."""

    name: str
    max_jobs: int
    skills: frozenset[str]
    id: UUID = field(default_factory=uuid4)
    job_ids: list[UUID] = field(default_factory=list)

    @property
    def load(self) -> int:
        return len(self.job_ids)

    def has_capacity(self) -> bool:
        return self.load < self.max_jobs

    def can_take(self, job: Job) -> bool:
        return self.has_capacity() and job.skill in self.skills

    def take(self, job: Job) -> None:
        """Assign the job to this technician, or refuse loudly."""
        if job.skill not in self.skills:
            raise SkillMismatch(f"{self.name} lacks skill '{job.skill}'")
        if not self.has_capacity():
            raise CapacityExceeded(f"{self.name} is at capacity ({self.max_jobs})")
        job.assign_to(self.id)  # validates the job's own state first
        self.job_ids.append(job.id)

    def release(self, job: Job) -> None:
        """Mark the job completed and free the slot."""
        if job.id not in self.job_ids:
            raise InvalidTransition(f"job {job.id} is not held by {self.name}")
        job.complete()
        self.job_ids.remove(job.id)
