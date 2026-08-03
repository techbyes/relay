import time
from datetime import datetime, timezone

from fastapi import HTTPException
import redis


class RateLimiter:
    """Redis-backed request throttling and monthly budget enforcement.

    Known trade-off: budget is checked against spend recorded *before* the
    current request started, since the real cost of a streaming request is
    only known once the provider finishes and reports token usage. That
    means a single in-flight request can push total spend slightly past the
    configured budget before the next request is blocked. A stricter design
    would reserve an estimated cost up front and reconcile afterwards, but
    that adds meaningful complexity for a marginal accuracy gain at this
    scale, so it's left as a documented limitation rather than solved here.
    """

    def __init__(self, redis_client: "redis.Redis"):
        self.redis = redis_client

    def check_request_rate(self, key_id: int, limit_per_minute: int) -> None:
        window = int(time.time() // 60)
        redis_key = f"ratelimit:{key_id}:{window}"
        current = self.redis.incr(redis_key)
        if current == 1:
            self.redis.expire(redis_key, 60)
        if current > limit_per_minute:
            raise HTTPException(status_code=429, detail="Rate limit exceeded, try again shortly")

    def check_budget(self, key_id: int, monthly_budget_usd: float) -> None:
        redis_key = self._spend_key(key_id)
        spent = float(self.redis.get(redis_key) or 0.0)
        if spent >= monthly_budget_usd:
            raise HTTPException(status_code=402, detail="Monthly budget exceeded for this API key")

    def record_spend(self, key_id: int, cost_usd: float) -> None:
        redis_key = self._spend_key(key_id)
        self.redis.incrbyfloat(redis_key, cost_usd)
        self.redis.expire(redis_key, 60 * 60 * 24 * 40)  # ~40 days, safely spans the current month

    @staticmethod
    def _spend_key(key_id: int) -> str:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return f"spend:{key_id}:{month}"
