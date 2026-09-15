import pytest

from dispatch_engine.domain import (
    Assignment,
    CapacityExceeded,
    DispatchEngine,
    DispatchRun,
    DispatchRunStatus,
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


def test_dispatch_all_assigns_what_it_can_and_skips_the_rest() -> None:
    t = tech(max_jobs=1)
    hvac_job, plumbing_job = Job(title="X", skill="hvac"), Job(title="Y", skill="plumbing")
    assignments = DispatchEngine().dispatch_all([hvac_job, plumbing_job], [t])
    assert assignments == [Assignment(job_id=hvac_job.id, technician_id=t.id)]
    assert hvac_job.status is JobStatus.ASSIGNED
    assert plumbing_job.status is JobStatus.PENDING  # no matching technician, left alone


def test_dispatch_all_on_empty_input_returns_empty() -> None:
    assert DispatchEngine().dispatch_all([], [tech()]) == []
    assert DispatchEngine().dispatch_all([Job(title="X", skill="hvac")], []) == []


def test_dispatch_all_stops_once_everyone_is_at_capacity() -> None:
    t = tech(max_jobs=1)
    jobs = [Job(title=f"J{i}", skill="hvac") for i in range(3)]
    assignments = DispatchEngine().dispatch_all(jobs, [t])
    assert len(assignments) == 1
    assert [j.status for j in jobs].count(JobStatus.ASSIGNED) == 1


def test_dispatch_run_starts() -> None:
    run = DispatchRun()
    run.start()
    assert run.status == DispatchRunStatus.RUNNING


def test_dispatch_run_succeeds_with_assignments() -> None:
    # One status assertion per test, each on its own DispatchRun: mypy's literal
    # narrowing does not know run.start()/succeed() mutate run.status, so two
    # checks against it in one function would report a false non-overlapping check.
    run = DispatchRun()
    run.start()
    assignment = Assignment(job_id=tech().id, technician_id=tech().id)
    run.succeed([assignment])
    assert run.status == DispatchRunStatus.SUCCEEDED
    assert run.assignments == [assignment]


def test_dispatch_run_failure() -> None:
    run = DispatchRun()
    run.start()
    run.fail("boom")
    assert run.status is DispatchRunStatus.FAILED
    assert run.error == "boom"


def test_dispatch_run_rejects_out_of_order_transitions() -> None:
    run = DispatchRun()
    with pytest.raises(InvalidTransition):
        run.succeed([])  # never started
    with pytest.raises(InvalidTransition):
        run.fail("boom")  # never started
    run.start()
    with pytest.raises(InvalidTransition):
        run.start()  # already running
