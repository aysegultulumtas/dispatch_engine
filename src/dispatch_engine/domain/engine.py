"""Assignment strategy. Kept behind one method so a solver can replace it later."""

from collections.abc import Iterable

from .exceptions import NoAvailableTechnician
from .models import Assignment, Job, Technician


class DispatchEngine:
    """Greedy dispatcher: least-loaded technician that has the required skill.

    Sufficient for a first version. The signature stays the same when this is
    swapped for a constraint solver (OR-Tools) running in a background worker.
    """

    def dispatch(self, job: Job, technicians: Iterable[Technician]) -> Technician:
        candidates = [t for t in technicians if t.can_take(job)]
        if not candidates:
            raise NoAvailableTechnician(f"no technician available for skill '{job.skill}'")
        chosen = min(candidates, key=lambda t: t.load)
        chosen.take(job)
        return chosen

    def dispatch_all(
        self, jobs: Iterable[Job], technicians: Iterable[Technician]
    ) -> list[Assignment]:
        """Dispatch every job that can currently be placed; skip the rest.

        Runs in the background worker (see dispatch_engine.worker), not a request
        handler, so unlike dispatch() it never raises for an unassignable job —
        one bad job in a batch must not sink the rest of the run.
        """
        technicians = list(technicians)
        assignments = []
        for job in jobs:
            try:
                chosen = self.dispatch(job, technicians)
            except NoAvailableTechnician:
                continue
            assignments.append(Assignment(job_id=job.id, technician_id=chosen.id))
        return assignments
