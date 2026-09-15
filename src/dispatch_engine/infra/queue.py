"""Redis connection + RQ queue. REDIS_URL is read from the environment, same
pattern as DATABASE_URL in db.py. Redis is transport only — a queued run's
state of record lives in Postgres (see DispatchRunRow), so a lost Redis job
never strands a run in an unknown state; it just never gets picked up."""

import os

from redis import Redis
from rq import Queue

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

redis_conn = Redis.from_url(REDIS_URL)
dispatch_queue = Queue("dispatch", connection=redis_conn)
