from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from dispatch_engine.domain import InvalidTransition, Job
from dispatch_engine.infra.repository import Repository as RepositoryProtocol

from ..deps import Engine, Repository
from ..schemas import JobCreate, JobRead

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _job_or_404(repo: RepositoryProtocol, job_id: UUID) -> Job:
    job = await repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return job


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, repo: Repository) -> JobRead:
    job = await repo.add_job(Job(title=payload.title, skill=payload.skill))
    return JobRead.from_domain(job)


@router.get("")
async def list_jobs(repo: Repository) -> list[JobRead]:
    return [JobRead.from_domain(j) for j in await repo.list_jobs()]


@router.get("/{job_id}")
async def get_job(job_id: UUID, repo: Repository) -> JobRead:
    return JobRead.from_domain(await _job_or_404(repo, job_id))


@router.post("/{job_id}/dispatch")
async def dispatch_job(job_id: UUID, repo: Repository, engine: Engine) -> JobRead:
    # Greedy dispatch is O(n) and cheap. A real solver must NOT run here;
    # it belongs in a background worker so the event loop stays responsive.
    job = await _job_or_404(repo, job_id)
    chosen = engine.dispatch(job, await repo.list_technicians())
    await repo.update_job(job)
    await repo.update_technician(chosen)
    return JobRead.from_domain(job)


@router.post("/{job_id}/complete")
async def complete_job(job_id: UUID, repo: Repository) -> JobRead:
    job = await _job_or_404(repo, job_id)
    if job.technician_id is None:
        raise InvalidTransition(f"job {job_id} has not been dispatched")
    technician = await repo.get_technician(job.technician_id)
    if technician is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="technician not found")
    technician.release(job)
    await repo.update_job(job)
    await repo.update_technician(technician)
    return JobRead.from_domain(job)
