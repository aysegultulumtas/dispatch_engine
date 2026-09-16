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
API_KEY=dev-local-key uv run uvicorn dispatch_engine.api.app:create_app --factory --reload  # terminal 1: API
uv run python -m dispatch_engine.worker                                                     # terminal 2: worker
```

`DATABASE_URL` / `REDIS_URL` default to
`postgresql+asyncpg://dispatch:dispatch@localhost:5432/dispatch` and
`redis://localhost:6379/0` (see `.env.example`). `API_KEY` has no default: the
API refuses to start without one (the app is a uvicorn `--factory` for exactly
that reason).

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
| GET    | `/dispatch-runs/{id}/events` | Server-Sent Events, closes on a terminal status |
| GET    | `/health`                 | liveness, no dependencies checked               |
| GET    | `/ready`                  | readiness, pings Postgres + Redis               |

### Authentication

Every endpoint except `/health`, `/ready` and the docs requires the header
`X-API-Key: <API_KEY>` (compared in constant time); missing or wrong → `401`.
The scheme is declared in OpenAPI, so `/docs` has an "Authorize" button.
Single shared key by design — see "Known limits".

### Idempotency

`POST /technicians`, `/jobs` and `/dispatch-runs` accept an optional
`Idempotency-Key` header (Stripe pattern). Replaying the same key with the same
body returns the original status and body without repeating the side effect;
the same key with a different body → `422`; a key whose first request is still
running → `409`. Keys are stored in Postgres (`idempotency_keys`) and expire
after 24 hours.

### Pagination

`GET /technicians` and `GET /jobs` are keyset-paginated on `(created_at, id)`:
`?limit=` (default 50, max 200) and `?cursor=`. The body stays a plain array;
when there is another page the response carries an `X-Next-Cursor` header —
pass it back as `?cursor=`. A cursor that does not decode → `422`.

### Live status (SSE)

`GET /dispatch-runs/{id}/events` is a `text/event-stream`: the current state
first, then one `data: <same JSON as GET /dispatch-runs/{id}>` event per status
change, closed after `succeeded`/`failed` (or after 10 minutes). Plain polling
of `GET /dispatch-runs/{id}` keeps working.

```sh
curl -N -H "X-API-Key: dev-local-key" http://localhost:8000/dispatch-runs/<id>/events
```

### Maintenance sweep

The worker runs a sweep at startup and then hourly (RQ's built-in scheduler,
`work(with_scheduler=True)`), with fixed rules: finished runs older than 30
days and idempotency keys older than 24 hours are deleted; a run `running` for
more than 15 minutes is failed as `stale: worker lost`; a run `queued` for
more than 5 minutes whose RQ job disappeared is re-enqueued under the same id.

### Observability

Logs are structured (structlog): human-readable on a TTY, JSON otherwise —
uvicorn and rq lines included. Every request gets an `X-Request-ID` (yours is
honoured, otherwise a uuid4), echoed on the response and attached to every log
line of that request; the worker attaches `run_id` the same way.

Tracing is OpenTelemetry (FastAPI, SQLAlchemy, Redis) and switches on only when
the standard `OTEL_EXPORTER_OTLP_ENDPOINT` is set (plus `OTEL_SERVICE_NAME` if
you like); without it no tracer is installed and nothing tries to export. When
on, `trace_id` is added to log lines. No collector ships with the compose
stack.

Rule violations (capacity, skill mismatch, invalid transition) return `409`;
malformed payloads return `422`. A single `/jobs/{id}/dispatch` call stays
synchronous and cheap; `/dispatch-runs` is for batch/solver-driven dispatch
(Faz 8) that would otherwise block the event loop — the worker (a separate
process, see `dispatch_engine.worker`) runs it and writes the result back to
Postgres, which stays the source of truth even if Redis is momentarily down.

## Known limits

- **Redis is a single instance (SPOF).** If it goes down, `POST /dispatch-runs`
  fails and the worker idles; already-recorded runs are safe because Postgres is
  the source of truth (Redis is transport only). Redis Sentinel (1 replica +
  3 sentinels, quorum 2) is the standard fix and is deliberately deferred until
  a real production deployment; it is not worth the operational surface for a
  local/portfolio stack.
- **One shared API key, no users or roles.** Enough to keep the API off the
  public internet; per-user auth (OAuth2/JWT) is only justified once there are
  multiple principals (a multi-user or SaaS deployment).
