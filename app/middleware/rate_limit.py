"""Rate limiting middleware using token bucket algorithm."""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict

from fastapi import HTTPException, Request, status

from app.core.config import settings


@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""

    capacity: int
    tokens: float = field(default=0.0)
    last_update: float = field(default_factory=time.time)
    refill_rate: float = field(default=0.0)  # tokens per second

    def __post_init__(self):
        self.tokens = float(self.capacity)
        self.refill_rate = self.capacity / settings.rate_limit_window

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if successful."""
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now

        # Refill tokens
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)

        # Try to consume
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def get_remaining(self) -> int:
        return int(self.tokens)

    def get_reset_time(self) -> int:
        """Get seconds until bucket is full."""
        tokens_needed = self.capacity - self.tokens
        if tokens_needed <= 0:
            return 0
        return int(tokens_needed / self.refill_rate)


class RateLimiter:
    """Rate limiter using token bucket per API key."""

    def __init__(self):
        self._buckets: Dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(capacity=settings.rate_limit_requests)
        )
        self._lock = Lock()

    def check_rate_limit(self, api_key: str, rate_limit: int = None) -> TokenBucket:
        """Check and consume rate limit for API key."""
        with self._lock:
            if api_key not in self._buckets:
                capacity = rate_limit or settings.rate_limit_requests
                self._buckets[api_key] = TokenBucket(capacity=capacity)

            bucket = self._buckets[api_key]

            if not bucket.consume():
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": {
                            "message": "Rate limit exceeded. Please retry after some time.",
                            "type": "rate_limit_error",
                            "code": "rate_limit_exceeded",
                        }
                    },
                    headers={
                        "X-RateLimit-Limit": str(bucket.capacity),
                        "X-RateLimit-Remaining": str(bucket.get_remaining()),
                        "X-RateLimit-Reset": str(bucket.get_reset_time()),
                        "Retry-After": str(bucket.get_reset_time()),
                    },
                )

            return bucket


# Global rate limiter instance
rate_limiter = RateLimiter()


async def check_rate_limit(request: Request):
    """Dependency to check rate limit."""
    if not settings.rate_limit_enabled:
        return

    api_key_info = getattr(request.state, "api_key_info", {})
    api_key = api_key_info.get("api_key", "anonymous")
    rate_limit = api_key_info.get("rate_limit")

    bucket = rate_limiter.check_rate_limit(api_key, rate_limit)

    # Add rate limit headers to response
    request.state.rate_limit_headers = {
        "X-RateLimit-Limit": str(bucket.capacity),
        "X-RateLimit-Remaining": str(bucket.get_remaining()),
        "X-RateLimit-Reset": str(bucket.get_reset_time()),
    }
