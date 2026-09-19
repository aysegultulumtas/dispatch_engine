"""Assignment strategy: greedy for one job, OR-Tools for a batch."""

from collections.abc import Iterable

from .exceptions import NoAvailableTechnician
from .models import Assignment, Job, Technician
from .optimizer import solve_assignments


class DispatchEngine:
    """dispatch() is greedy (least-loaded technician with the skill) and stays
    cheap enough for a request handler; dispatch_all() hands the whole batch to
    the min-cost-flow model in optimizer.py and runs in the background worker.
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
        """Place as many of the jobs as possible, balancing load; skip the rest.

        Runs in the background worker (see dispatch_engine.worker), not a request
        handler, so unlike dispatch() it never raises for an unassignable job —
        one bad job in a batch must not sink the rest of the run. Unlike a greedy
        pass it is order-independent: a job never loses its only technician to
        an earlier job that had another option (see optimizer.py).
        """
        return solve_assignments(list(jobs), list(technicians))
