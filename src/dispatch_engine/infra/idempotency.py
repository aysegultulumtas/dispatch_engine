"""Idempotency-Key storage (Stripe pattern).

Postgres, not Redis: Redis is transport only (see queue.py), and a replayed POST
must still return the original response after the broker has been restarted or
flushed. Keys live for 24 hours and are removed by the worker's maintenance
sweep (see worker/maintenance.py).

Two implementations, same split as Repository: Postgres for the real app,
in-memory for tests that do not need a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from .orm import IdempotencyKeyRow

KEY_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class IdempotencyRecord:
    """A claimed key. status_code is None while the first request is still running."""

    request_hash: str
    status_code: int | None
    response_body: Any


class IdempotencyStore(Protocol):
    async def reserve(self, key: str, request_hash: str) -> IdempotencyRecord | None:
        """Claim the key. Returns None if we got it, else the record that beat us."""

    async def complete(self, key: str, status_code: int, response_body: Any) -> None: ...

    async def release(self, key: str) -> None:
        """Drop an unfinished reservation so the caller may retry."""

    async def purge_expired(self, cutoff: datetime) -> int: ...


class PostgresIdempotencyStore:
    """Owns its own short transactions: the reservation must be visible to a
    concurrent request before the handler it guards has committed anything."""

    def __init__(self, session_maker: async_sessionmaker[Any]) -> None:
        self._session_maker = session_maker

    async def reserve(self, key: str, request_hash: str) -> IdempotencyRecord | None:
        async with self._session_maker() as session:
            session.add(IdempotencyKeyRow(key=key, request_hash=request_hash))
            try:
                await session.commit()
            except IntegrityError:
                # Someone else inserted the same primary key first.
                await session.rollback()
            else:
                return None

            row = (
                await session.execute(select(IdempotencyKeyRow).where(IdempotencyKeyRow.key == key))
            ).scalar_one()
            return IdempotencyRecord(row.request_hash, row.status_code, row.response_body)

    async def complete(self, key: str, status_code: int, response_body: Any) -> None:
        async with self._session_maker() as session:
            row = await session.get(IdempotencyKeyRow, key)
            if row is None:  # pragma: no cover - swept away mid-request
                return
            row.status_code = status_code
            row.response_body = response_body
            await session.commit()

    async def release(self, key: str) -> None:
        async with self._session_maker() as session:
            await session.execute(delete(IdempotencyKeyRow).where(IdempotencyKeyRow.key == key))
            await session.commit()

    async def purge_expired(self, cutoff: datetime) -> int:
        async with self._session_maker() as session:
            result = await session.execute(
                delete(IdempotencyKeyRow).where(IdempotencyKeyRow.created_at < cutoff)
            )
            await session.commit()
            return int(result.rowcount)


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[str, tuple[IdempotencyRecord, datetime]] = {}

    async def reserve(self, key: str, request_hash: str) -> IdempotencyRecord | None:
        existing = self._records.get(key)
        if existing is not None:
            return existing[0]
        self._records[key] = (IdempotencyRecord(request_hash, None, None), datetime.now(UTC))
        return None

    async def complete(self, key: str, status_code: int, response_body: Any) -> None:
        record, created_at = self._records[key]
        self._records[key] = (
            IdempotencyRecord(record.request_hash, status_code, response_body),
            created_at,
        )

    async def release(self, key: str) -> None:
        self._records.pop(key, None)

    async def purge_expired(self, cutoff: datetime) -> int:
        stale = [k for k, (_, created_at) in self._records.items() if created_at < cutoff]
        for key in stale:
            del self._records[key]
        return len(stale)
