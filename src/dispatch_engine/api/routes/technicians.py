from fastapi import APIRouter, status

from dispatch_engine.domain import Technician

from ..deps import Repository
from ..schemas import TechnicianCreate, TechnicianRead

router = APIRouter(prefix="/technicians", tags=["technicians"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_technician(payload: TechnicianCreate, repo: Repository) -> TechnicianRead:
    technician = Technician(
        name=payload.name, max_jobs=payload.max_jobs, skills=frozenset(payload.skills)
    )
    await repo.add_technician(technician)
    return TechnicianRead.from_domain(technician)


@router.get("")
async def list_technicians(repo: Repository) -> list[TechnicianRead]:
    return [TechnicianRead.from_domain(t) for t in await repo.list_technicians()]
