"""Worker entrypoint: `python -m dispatch_engine.worker` (see docker-compose.yml).

RQ's default Worker forks a child process per job (os.fork), which Windows does
not have. SimpleWorker runs jobs in-process instead, at the cost of not
recovering from a job that segfaults or hangs — an acceptable trade for local
Windows dev; the Linux container always uses the forking Worker.

with_scheduler=True starts RQ's scheduler process alongside, which is what turns
the maintenance sweep's hourly Repeat into actual enqueues (see maintenance.py).
"""

import sys

from rq import SimpleWorker, Worker

from ..infra.queue import dispatch_queue, redis_conn
from ..observability import configure_logging, configure_tracing
from .maintenance import schedule_sweeps

WorkerClass = SimpleWorker if sys.platform == "win32" else Worker

if __name__ == "__main__":
    configure_logging()
    configure_tracing()
    schedule_sweeps(dispatch_queue)
    WorkerClass([dispatch_queue], connection=redis_conn).work(with_scheduler=True)
