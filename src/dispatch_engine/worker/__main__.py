"""Worker entrypoint: `python -m dispatch_engine.worker` (see docker-compose.yml).

RQ's default Worker forks a child process per job (os.fork), which Windows does
not have. SimpleWorker runs jobs in-process instead, at the cost of not
recovering from a job that segfaults or hangs — an acceptable trade for local
Windows dev; the Linux container always uses the forking Worker.
"""

import sys

from rq import SimpleWorker, Worker

from ..infra.queue import dispatch_queue, redis_conn

WorkerClass = SimpleWorker if sys.platform == "win32" else Worker

if __name__ == "__main__":
    WorkerClass([dispatch_queue], connection=redis_conn).work()
