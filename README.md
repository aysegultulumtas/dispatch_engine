# dispatch-engine

Capacity- and skill-aware job assignment for field-service technicians.
A modular monolith: framework-free domain rules, a FastAPI edge, and a
PostgreSQL repository behind a small protocol.

```
api/      FastAPI routes + Pydantic schemas   (HTTP shape only)
domain/   Job, Technician, DispatchEngine     (rules, no framework imports)
infra/    SQLAlchemy 2.0 async + Alembic      (storage shape only)
```

## Run with Docker

```sh
docker compose up --build
```

Starts Postgres + Redis, applies migrations (`migrate` service), then serves
the API on <http://localhost:8000> and starts the background `worker`.
Interactive docs: <http://localhost:8000/docs>.

## Run locally

Requires [uv](https://docs.astral.sh/uv/) and Docker (for Postgres + Redis).

```sh
uv sync                                  # creates .venv with dev tools
docker compose up -d postgres redis
uv run alembic upgrade head
uv run uvicorn dispatch_engine.api.app:app --reload   # terminal 1: API
uv run python -m dispatch_engine.worker                # terminal 2: worker
```

`DATABASE_URL` / `REDIS_URL` default to
`postgresql+asyncpg://dispatch:dispatch@localhost:5432/dispatch` and
`redis://localhost:6379/0` (see `.env.example`).

**Windows:** the worker auto-selects RQ's `SimpleWorker` (in-process, no
`os.fork`) when `sys.platform == "win32"`; the container always uses the
regular forking `Worker` on Linux.

## Test

```sh
uv run pytest                            # unit + API tests, in-memory repository
uv run pytest --cov                      # with coverage report
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Postgres-backed tests run against a separate `dispatch_test` database (created
by `docker/init-test-db.sql`) and skip when it is unreachable; in CI they are
required.

## API

| Method | Path                      | Notes                                          |
| ------ | ------------------------- | ----------------------------------------------- |
| POST   | `/technicians`            | `{name, max_jobs, skills[]}`                    |
| GET    | `/technicians`            | includes current `load`                         |
| POST   | `/jobs`                   | `{title, skill}`                                |
| GET    | `/jobs`, `/jobs/{id}`     |                                                  |
| POST   | `/jobs/{id}/dispatch`     | synchronous; least-loaded technician with skill |
| POST   | `/jobs/{id}/complete`     | frees the technician's slot                     |
| POST   | `/dispatch-runs`          | `202`; queues "dispatch every pending job"      |
| GET    | `/dispatch-runs/{id}`     | poll for `queued\|running\|succeeded\|failed`   |
| GET    | `/health`                 | liveness, no dependencies checked               |
| GET    | `/ready`                  | readiness, pings Postgres + Redis               |

Rule violations (capacity, skill mismatch, invalid transition) return `409`;
malformed payloads return `422`. A single `/jobs/{id}/dispatch` call stays
synchronous and cheap; `/dispatch-runs` is for batch/solver-driven dispatch
(Faz 8) that would otherwise block the event loop — the worker (a separate
process, see `dispatch_engine.worker`) runs it and writes the result back to
Postgres, which stays the source of truth even if Redis is momentarily down.
