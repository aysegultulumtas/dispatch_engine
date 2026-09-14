import pytest

from dispatch_engine.domain import (
    CapacityExceeded,
    DispatchEngine,
    InvalidTransition,
    Job,
    JobStatus,
    NoAvailableTechnician,
    SkillMismatch,
    Technician,
)


def tech(name: str = "Ada", max_jobs: int = 2, *skills: str) -> Technician:
    return Technician(name=name, max_jobs=max_jobs, skills=frozenset(skills or ("hvac",)))


def test_technician_takes_job_within_capacity() -> None:
    t, job = tech(), Job(title="Fix AC", skill="hvac")
    t.take(job)
    assert job.status is JobStatus.ASSIGNED
    assert job.technician_id == t.id
    assert t.load == 1


def test_technician_refuses_over_capacity() -> None:
    t = tech(max_jobs=1)
    t.take(Job(title="A", skill="hvac"))
    with pytest.raises(CapacityExceeded):
        t.take(Job(title="B", skill="hvac"))
    assert t.load == 1


def test_technician_refuses_unknown_skill() -> None:
    with pytest.raises(SkillMismatch):
        tech().take(Job(title="Rewire", skill="electrical"))


def test_job_lifecycle_and_release() -> None:
    t, job = tech(), Job(title="Fix AC", skill="hvac")
    t.take(job)
    t.release(job)
    assert job.status is JobStatus.COMPLETED
    assert t.load == 0


def test_invalid_transitions_are_rejected() -> None:
    job = Job(title="Fix AC", skill="hvac")
    with pytest.raises(InvalidTransition):
        job.complete()  # never assigned
    t = tech()
    t.take(job)
    with pytest.raises(InvalidTransition):
        tech("Bob").release(job)  # held by someone else
    t.release(job)
    with pytest.raises(InvalidTransition):
        t.take(job)  # already completed


def test_engine_prefers_least_loaded_matching_skill() -> None:
    busy, free, wrong = tech("Busy"), tech("Free"), tech("Wrong", 2, "plumbing")
    busy.take(Job(title="X", skill="hvac"))
    chosen = DispatchEngine().dispatch(Job(title="Y", skill="hvac"), [busy, free, wrong])
    assert chosen is free


def test_engine_raises_when_nobody_can_take_it() -> None:
    t = tech(max_jobs=1)
    t.take(Job(title="X", skill="hvac"))
    with pytest.raises(NoAvailableTechnician):
        DispatchEngine().dispatch(Job(title="Y", skill="hvac"), [t])
