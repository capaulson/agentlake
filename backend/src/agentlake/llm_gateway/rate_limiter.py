"""Redis-backed rate limiter for the LLM Gateway."""

from __future__ import annotations

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Sliding-window rate limiter backed by Redis INCR + EXPIRE.

    Supports scoped rate limiting at global, per-service, and per-provider
    levels.  Each scope maintains independent counters.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window_seconds: int = 60,
        scope: str = "global",
    ) -> tuple[bool, int, int]:
        """Check whether a request is within the rate limit.

        Uses a fixed-window counter: increments the key and sets an expiry
        equal to ``window_seconds`` on first access.

        Args:
            key: Identifier for the rate-limit bucket (e.g. service name,
                provider name, or a composite).
            limit: Maximum number of requests allowed in the window.
            window_seconds: Window duration in seconds.
            scope: Namespace prefix (``global``, ``per_service``,
                ``per_provider``).

        Returns:
            Tuple of ``(allowed, remaining, reset_seconds)``.
            *allowed* is ``True`` if the request should proceed.
            *remaining* is the number of requests left in the window.
            *reset_seconds* is the TTL until the counter resets.
        """
        redis_key = f"ratelimit:{scope}:{key}"

        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.incr(redis_key)
            pipe.ttl(redis_key)
            results = await pipe.execute()

            current_count: int = results[0]
            ttl: int = results[1]

            # First request in this window — set the expiry.
            if ttl == -1:
                await self._redis.expire(redis_key, window_seconds)
                ttl = window_seconds

            allowed = current_count <= limit
            remaining = max(0, limit - current_count)
            reset_seconds = max(0, ttl)

            if not allowed:
                logger.warning(
                    "rate_limit_exceeded",
                    key=key,
                    scope=scope,
                    current=current_count,
                    limit=limit,
                )

            return allowed, remaining, reset_seconds

        except Exception as exc:
            # If Redis is down, fail open (allow the request) rather than
            # blocking the entire gateway.
            logger.error(
                "rate_limiter_redis_error",
                error=str(exc),
                key=key,
                scope=scope,
            )
            return True, limit, window_seconds
