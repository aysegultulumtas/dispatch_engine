"""Assignment strategy. Kept behind one method so a solver can replace it later."""

from collections.abc import Iterable

from .exceptions import NoAvailableTechnician
from .models import Job, Technician


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
