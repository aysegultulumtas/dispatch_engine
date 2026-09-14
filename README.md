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

Starts Postgres, applies migrations (`migrate` service), then serves the API
on <http://localhost:8000>. Interactive docs: <http://localhost:8000/docs>.

## Run locally

Requires [uv](https://docs.astral.sh/uv/) and Docker (for Postgres).

```sh
uv sync                                  # creates .venv with dev tools
docker compose up -d postgres
uv run alembic upgrade head
uv run uvicorn dispatch_engine.api.app:app --reload
```

`DATABASE_URL` defaults to `postgresql+asyncpg://dispatch:dispatch@localhost:5432/dispatch`
(see `.env.example`).

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

| Method | Path                    | Notes                                   |
| ------ | ----------------------- | --------------------------------------- |
| POST   | `/technicians`          | `{name, max_jobs, skills[]}`            |
| GET    | `/technicians`          | includes current `load`                 |
| POST   | `/jobs`                 | `{title, skill}`                        |
| GET    | `/jobs`, `/jobs/{id}`   |                                         |
| POST   | `/jobs/{id}/dispatch`   | least-loaded technician with the skill  |
| POST   | `/jobs/{id}/complete`   | frees the technician's slot             |
| GET    | `/health`               | liveness, no dependencies checked       |
| GET    | `/ready`                | readiness, pings the database           |

Rule violations (capacity, skill mismatch, invalid transition) return `409`;
malformed payloads return `422`.
