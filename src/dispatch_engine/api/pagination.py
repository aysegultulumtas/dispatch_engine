"""Keyset pagination on (created_at, id).

The body stays a plain JSON array (the UI depends on that shape); the position of
the next page travels in the X-Next-Cursor response header and is absent on the
last page. A cursor is the last row's `created_at|id`, urlsafe-base64 so it is
opaque to clients and safe in a query string.
"""

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response

from dispatch_engine.infra.repository import Keyset

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
NEXT_CURSOR_HEADER = "X-Next-Cursor"


class _HasKeyset(Protocol):
    @property
    def id(self) -> UUID: ...
    @property
    def created_at(self) -> datetime: ...


def encode_cursor(item: _HasKeyset) -> str:
    raw = f"{item.created_at.isoformat()}|{item.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> Keyset:
    try:
        created_at, _, id_ = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return datetime.fromisoformat(created_at), UUID(id_)
    except ValueError as exc:  # bad base64, bad timestamp, bad uuid
        raise HTTPException(status_code=422, detail="invalid cursor") from exc


@dataclass(frozen=True)
class Page:
    limit: int
    after: Keyset | None

    @property
    def fetch_limit(self) -> int:
        return self.limit + 1  # one extra row tells us whether another page exists

    def apply[T: _HasKeyset](self, items: Sequence[T], response: Response) -> list[T]:
        """Trim a fetch_limit-sized result to the page and announce the next cursor."""
        if len(items) > self.limit:
            items = items[: self.limit]
            response.headers[NEXT_CURSOR_HEADER] = encode_cursor(items[-1])
        return list(items)


def page_params(
    limit: Annotated[int, Query(ge=1, description=f"page size, capped at {MAX_LIMIT}")] = (
        DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query(description="X-Next-Cursor of the previous page")] = None,
) -> Page:
    return Page(limit=min(limit, MAX_LIMIT), after=decode_cursor(cursor) if cursor else None)


PageParams = Annotated[Page, Depends(page_params)]
