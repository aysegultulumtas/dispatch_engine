"""Request/response contracts. Shape and type checks only; business rules live in domain/."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from dispatch_engine.domain import DispatchRun, DispatchRunStatus, Job, JobStatus, Technician

NonEmptyStr = Annotated[str, Field(min_length=1, max_length=100)]


class TechnicianCreate(BaseModel):
    name: NonEmptyStr
    max_jobs: int = Field(ge=1, le=100)
    skills: list[NonEmptyStr] = Field(min_length=1)


class TechnicianRead(BaseModel):
    id: UUID
    name: str
    max_jobs: int
    skills: list[str]
    load: int

    @classmethod
    def from_domain(cls, t: Technician) -> "TechnicianRead":
        return cls(id=t.id, name=t.name, max_jobs=t.max_jobs, skills=sorted(t.skills), load=t.load)


class JobCreate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    skill: NonEmptyStr


class JobRead(BaseModel):
    id: UUID
    title: str
    skill: str
    status: JobStatus
    technician_id: UUID | None

    @classmethod
    def from_domain(cls, j: Job) -> "JobRead":
        return cls(
            id=j.id, title=j.title, skill=j.skill, status=j.status, technician_id=j.technician_id
        )


class AssignmentRead(BaseModel):
    job_id: UUID
    technician_id: UUID


class DispatchRunRead(BaseModel):
    id: UUID
    status: DispatchRunStatus
    assignments: list[AssignmentRead]
    error: str | None

    @classmethod
    def from_domain(cls, r: DispatchRun) -> "DispatchRunRead":
        return cls(
            id=r.id,
            status=r.status,
            assignments=[
                AssignmentRead(job_id=a.job_id, technician_id=a.technician_id)
                for a in r.assignments
            ],
            error=r.error,
        )
