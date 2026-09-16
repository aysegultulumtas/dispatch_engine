"""Idempotency-Key middleware (Stripe pattern).

A middleware rather than a dependency because the value being cached is the
*response*, which a dependency never sees. The header is optional; without it
nothing changes. Storage lives in infra (see infra/idempotency.py) and is held
on app.state so tests can swap in the in-memory implementation.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from dispatch_engine.infra.idempotency import IdempotencyStore

# Creating endpoints only: the rest are either reads or already idempotent by id.
IDEMPOTENT_PATHS = frozenset({"/v1/technicians", "/v1/jobs", "/v1/dispatch-runs"})

HEADER = "Idempotency-Key"


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        key = request.headers.get(HEADER)
        if key is None or request.method != "POST" or request.url.path not in IDEMPOTENT_PATHS:
            return await call_next(request)

        body = await request.body()
        request_hash = hashlib.sha256(request.url.path.encode() + b"\0" + body).hexdigest()
        store: IdempotencyStore = request.app.state.idempotency_store

        existing = await store.reserve(key, request_hash)
        if existing is not None:
            if existing.request_hash != request_hash:
                return JSONResponse(
                    status_code=422,
                    content={"detail": f"{HEADER} was already used with a different request"},
                )
            if existing.status_code is None:
                # Reserved but not finished: a concurrent request owns this key.
                return JSONResponse(
                    status_code=409,
                    content={"detail": f"a request with this {HEADER} is in progress"},
                )
            return JSONResponse(status_code=existing.status_code, content=existing.response_body)

        try:
            response = await call_next(request)
            response_body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
        except Exception:
            await store.release(key)
            raise

        if 200 <= response.status_code < 300:
            await store.complete(key, response.status_code, json.loads(response_body))
        else:
            # Nothing durable happened; let the client fix the request and retry
            # with the same key rather than locking them out for 24 hours.
            await store.release(key)

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
