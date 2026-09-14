import pytest
from pydantic import ValidationError

from dispatch_engine.api.schemas import JobCreate, TechnicianCreate


def test_valid_technician_payload() -> None:
    t = TechnicianCreate(name="Ada", max_jobs=3, skills=["hvac", "plumbing"])
    assert t.max_jobs == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "max_jobs": 1, "skills": ["hvac"]},
        {"name": "Ada", "max_jobs": 0, "skills": ["hvac"]},
        {"name": "Ada", "max_jobs": "three", "skills": ["hvac"]},
        {"name": "Ada", "max_jobs": 1, "skills": []},
        {"name": "Ada", "max_jobs": 1, "skills": [""]},
        {"name": "Ada", "skills": ["hvac"]},
    ],
)
def test_invalid_technician_payload_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        TechnicianCreate(**payload)


@pytest.mark.parametrize("payload", [{"title": "", "skill": "hvac"}, {"title": "Fix AC"}])
def test_invalid_job_payload_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        JobCreate(**payload)
