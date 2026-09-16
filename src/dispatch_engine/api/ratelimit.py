"""Per-API-key rate limit on every /v1 route (see infra/ratelimit.py for the bucket).

Runs after require_api_key, so only authenticated callers spend tokens. The
bucket is keyed by a hash of the key, never the secret itself. If Redis is
down the request is allowed and a warning is logged (fail-open): the broker
being unavailable already stops batch dispatch, and taking the whole API down
with it would turn one outage into two.
"""

import hashlib
from typing import Annotated

import structlog
from fastapi import HTTPException, Request, Security, status
from redis.exceptions import RedisError

from dispatch_engine.infra.ratelimit import RedisTokenBucket

from .security import api_key_header

log = structlog.get_logger(__name__)


async def rate_limit(request: Request, presented: Annotated[str, Security(api_key_header)]) -> None:
    limiter: RedisTokenBucket = request.app.state.rate_limiter
    caller = hashlib.sha256(presented.encode()).hexdigest()[:16]
    try:
        decision = await limiter.take(caller)
    except RedisError as exc:
        log.warning("rate limiter unavailable, allowing request", error=str(exc))
        return
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={"Retry-After": str(decision.retry_after)},
        )
