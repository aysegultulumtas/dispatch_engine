"""Batch assignment as a min-cost max-flow problem (OR-Tools).

Greedy dispatch (DispatchEngine.dispatch) is order-dependent: the first job in
line can take the only technician a later job could have used. dispatch_all
therefore looks at the whole batch at once and solves it as a flow network:

    job --(cap 1, cost 0)--> technician with the skill --(cap 1, cost load+k)--> sink

Every job supplies one unit. Every technician has one unit-capacity arc to the
sink per free slot, priced at current load + k for k = 1..free, so each extra
job on the same technician costs one more than the last. solve_max_flow_with_min_cost
then delivers both objectives in order, in one polynomial-time solve: the
maximum flow is the largest number of jobs that can be placed at all, and among
those solutions the cheapest is the one whose resulting per-technician loads
are most even (the rising slot prices make a second job on someone dearer than
a first job on someone else). No time limit is needed; this is not a search.

There is no location, travel time or priority in the model, so this is a
capacitated bipartite assignment, not a routing (VRP) problem — which is why
ortools.graph is used and not the routing solver or CP-SAT.
"""

from ortools.graph.python import min_cost_flow

from .models import Assignment, Job, Technician


def solve_assignments(jobs: list[Job], technicians: list[Technician]) -> list[Assignment]:
    """Place as many jobs as possible, evenly, and apply the result via Technician.take()."""
    candidates = [(job, t) for job in jobs for t in technicians if t.can_take(job)]
    if not candidates:
        return []  # empty batch, nobody free, or no skill matches — nothing to solve

    job_node = {job.id: n for n, job in enumerate(jobs)}
    tech_node = {t.id: n for n, t in enumerate(technicians, start=len(jobs))}
    sink = len(jobs) + len(technicians)

    smcf = min_cost_flow.SimpleMinCostFlow()
    for node in job_node.values():
        smcf.set_node_supply(node, 1)
    arcs = [
        (smcf.add_arc_with_capacity_and_unit_cost(job_node[job.id], tech_node[t.id], 1, 0), job, t)
        for job, t in candidates
    ]
    for t in technicians:
        for slot in range(1, t.max_jobs - t.load + 1):
            smcf.add_arc_with_capacity_and_unit_cost(tech_node[t.id], sink, 1, t.load + slot)
    smcf.set_node_supply(sink, -len(jobs))

    # The shipped stub leaves this one method unannotated; everything else is typed.
    status = smcf.solve_max_flow_with_min_cost()  # type: ignore[no-untyped-call]
    if status != smcf.OPTIMAL:
        raise RuntimeError(f"min-cost-flow solver did not reach OPTIMAL: {status}")

    assignments = []
    for arc, job, t in arcs:  # arcs are in job order, so assignments are too
        if smcf.flow(arc):
            t.take(job)  # re-checks skill and capacity; the flow already respects both
            assignments.append(Assignment(job_id=job.id, technician_id=t.id))
    return assignments
