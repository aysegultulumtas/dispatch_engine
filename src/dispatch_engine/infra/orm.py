"""SQLAlchemy row models. Storage shape only — domain rules never live here."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import ARRAY, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class TechnicianRow(Base):
    __tablename__ = "technicians"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    max_jobs: Mapped[int]
    skills: Mapped[list[str]] = mapped_column(ARRAY(String))

    jobs: Mapped[list[JobRow]] = relationship(back_populates="technician")


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200))
    skill: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    technician_id: Mapped[UUID | None] = mapped_column(ForeignKey("technicians.id"), nullable=True)

    technician: Mapped[TechnicianRow | None] = relationship(back_populates="jobs")


class DispatchRunRow(Base):
    __tablename__ = "dispatch_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(String(20))
    # [{"job_id": "...", "technician_id": "..."}, ...] — UUIDs as strings, since
    # asyncpg's JSON codec does not serialize UUID objects.
    assignments: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
