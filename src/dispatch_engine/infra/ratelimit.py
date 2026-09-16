"""Token bucket in Redis, one bucket per caller, refilled continuously.

The whole check-and-decrement runs as one Lua script so two API processes can
never both spend the last token. Redis' own clock (TIME) is the reference, so
skew between API replicas does not matter. Limits are fixed: 120 requests of
burst, refilled at 60 per minute.
"""

from dataclasses import dataclass

from redis.asyncio import Redis

CAPACITY = 120
REFILL_PER_MINUTE = 60

_TAKE = """
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000

local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(bucket[1])
local ts = tonumber(bucket[2])
if tokens == nil then
  tokens = capacity
  ts = now
end
tokens = math.min(capacity, tokens + (now - ts) * refill_per_sec)

local allowed = 0
local retry_after = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_after = math.ceil((1 - tokens) / refill_per_sec)
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / refill_per_sec) + 1)
return {allowed, retry_after}
"""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int  # seconds until one token is back; 0 when allowed


class RedisTokenBucket:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._take = redis.register_script(_TAKE)

    async def take(self, caller: str) -> Decision:
        """Spend one token from `caller`'s bucket. Raises redis.RedisError when
        Redis cannot be reached — the caller decides what that means."""
        allowed, retry_after = await self._take(
            keys=[f"ratelimit:{caller}"], args=[CAPACITY, REFILL_PER_MINUTE / 60]
        )
        return Decision(allowed=bool(allowed), retry_after=int(retry_after))

    async def aclose(self) -> None:
        await self._redis.aclose()
