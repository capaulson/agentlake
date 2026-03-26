"""Tests for the Redis-backed rate limiter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agentlake.llm_gateway.rate_limiter import RateLimiter


@pytest.fixture()
def mock_redis() -> MagicMock:
    """Create a mock async Redis client.

    redis.pipeline() is synchronous and returns a pipeline object.
    The pipeline's execute() is async.
    """
    redis = MagicMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[1, -1])
    pipe.incr = MagicMock(return_value=pipe)
    pipe.ttl = MagicMock(return_value=pipe)
    redis.pipeline = MagicMock(return_value=pipe)
    redis.expire = AsyncMock(return_value=True)
    return redis


@pytest.fixture()
def rate_limiter(mock_redis: MagicMock) -> RateLimiter:
    return RateLimiter(redis=mock_redis)


class TestRateLimiter:
    """Tests for the RateLimiter."""

    @pytest.mark.asyncio
    async def test_allows_under_limit(
        self, rate_limiter: RateLimiter, mock_redis: MagicMock
    ) -> None:
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [1, 60]

        allowed, remaining, reset = await rate_limiter.check_rate_limit(
            key="test-service", limit=10, window_seconds=60
        )
        assert allowed is True
        assert remaining == 9
        assert reset == 60

    @pytest.mark.asyncio
    async def test_blocks_over_limit(
        self, rate_limiter: RateLimiter, mock_redis: MagicMock
    ) -> None:
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [11, 30]

        allowed, remaining, reset = await rate_limiter.check_rate_limit(
            key="test-service", limit=10, window_seconds=60
        )
        assert allowed is False
        assert remaining == 0
        assert reset == 30

    @pytest.mark.asyncio
    async def test_at_exact_limit(
        self, rate_limiter: RateLimiter, mock_redis: MagicMock
    ) -> None:
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [10, 45]

        allowed, remaining, reset = await rate_limiter.check_rate_limit(
            key="test-service", limit=10, window_seconds=60
        )
        assert allowed is True
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_first_request_sets_expiry(
        self, rate_limiter: RateLimiter, mock_redis: MagicMock
    ) -> None:
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [1, -1]  # TTL=-1 means no expiry set

        await rate_limiter.check_rate_limit(
            key="new-key", limit=10, window_seconds=60
        )
        mock_redis.expire.assert_called_once_with("ratelimit:global:new-key", 60)

    @pytest.mark.asyncio
    async def test_custom_scope(
        self, rate_limiter: RateLimiter, mock_redis: MagicMock
    ) -> None:
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [1, -1]

        await rate_limiter.check_rate_limit(
            key="anthropic", limit=100, window_seconds=60, scope="per_provider"
        )
        mock_redis.expire.assert_called_once_with("ratelimit:per_provider:anthropic", 60)

    @pytest.mark.asyncio
    async def test_redis_failure_fails_open(
        self, rate_limiter: RateLimiter, mock_redis: MagicMock
    ) -> None:
        """When Redis is down, the limiter should fail open (allow requests)."""
        pipe = mock_redis.pipeline.return_value
        pipe.execute.side_effect = ConnectionError("Redis unavailable")

        allowed, remaining, reset = await rate_limiter.check_rate_limit(
            key="test", limit=10, window_seconds=60
        )
        assert allowed is True
        assert remaining == 10
        assert reset == 60

    @pytest.mark.asyncio
    async def test_remaining_is_non_negative(
        self, rate_limiter: RateLimiter, mock_redis: MagicMock
    ) -> None:
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [100, 10]

        allowed, remaining, reset = await rate_limiter.check_rate_limit(
            key="test", limit=10, window_seconds=60
        )
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_different_window_size(
        self, rate_limiter: RateLimiter, mock_redis: MagicMock
    ) -> None:
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [1, -1]

        await rate_limiter.check_rate_limit(
            key="hourly", limit=1000, window_seconds=3600
        )
        mock_redis.expire.assert_called_once_with("ratelimit:global:hourly", 3600)
