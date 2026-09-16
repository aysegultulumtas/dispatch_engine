"""Core entities. Framework-free on purpose: no Pydantic, no ORM, only rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

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
class JobEvent:
    """Append-only audit record: one status transition of one job, and who did it
    ("api" for a request, "worker:<run_id>" for a batch run)."""

    job_id: UUID
    from_status: JobStatus
    to_status: JobStatus
    technician_id: UUID | None
    actor: str
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Technician:
    """A worker with a skill set and a hard cap on concurrent jobs."""

    name: str
    max_jobs: int
    skills: frozenset[str]
    id: UUID = field(default_factory=uuid4)
    job_ids: list[UUID] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

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


class DispatchRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class Assignment:
    """One job handed to one technician, produced by a completed DispatchRun."""

    job_id: UUID
    technician_id: UUID


@dataclass
class DispatchRun:
    """A background 'dispatch every pending job' request. Lifecycle:
    queued -> running -> (succeeded | failed). Runs in a worker (see
    dispatch_engine.worker); the API only creates and polls these."""

    id: UUID = field(default_factory=uuid4)
    status: DispatchRunStatus = DispatchRunStatus.QUEUED
    assignments: list[Assignment] = field(default_factory=list)
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def start(self) -> None:
        if self.status is not DispatchRunStatus.QUEUED:
            raise InvalidTransition(f"dispatch run {self.id} is {self.status}, cannot start")
        self.status = DispatchRunStatus.RUNNING

    def succeed(self, assignments: list[Assignment]) -> None:
        if self.status is not DispatchRunStatus.RUNNING:
            raise InvalidTransition(f"dispatch run {self.id} is {self.status}, cannot succeed")
        self.assignments = assignments
        self.status = DispatchRunStatus.SUCCEEDED

    def fail(self, error: str) -> None:
        if self.status is not DispatchRunStatus.RUNNING:
            raise InvalidTransition(f"dispatch run {self.id} is {self.status}, cannot fail")
        self.error = error
        self.status = DispatchRunStatus.FAILED
