import fakeredis
import pytest
from fastapi import HTTPException

from app.rate_limit import RateLimiter


def test_rate_limit_blocks_after_threshold():
    limiter = RateLimiter(fakeredis.FakeRedis(decode_responses=True))
    for _ in range(3):
        limiter.check_request_rate(key_id=1, limit_per_minute=3)

    with pytest.raises(HTTPException) as exc:
        limiter.check_request_rate(key_id=1, limit_per_minute=3)
    assert exc.value.status_code == 429


def test_different_keys_have_independent_limits():
    limiter = RateLimiter(fakeredis.FakeRedis(decode_responses=True))
    for _ in range(3):
        limiter.check_request_rate(key_id=1, limit_per_minute=3)
    # key 2 should not be affected by key 1's usage
    limiter.check_request_rate(key_id=2, limit_per_minute=3)


def test_budget_blocks_when_exhausted():
    limiter = RateLimiter(fakeredis.FakeRedis(decode_responses=True))
    limiter.record_spend(key_id=1, cost_usd=10.5)

    with pytest.raises(HTTPException) as exc:
        limiter.check_budget(key_id=1, monthly_budget_usd=10.0)
    assert exc.value.status_code == 402


def test_budget_allows_when_under_limit():
    limiter = RateLimiter(fakeredis.FakeRedis(decode_responses=True))
    limiter.record_spend(key_id=1, cost_usd=1.0)
    limiter.check_budget(key_id=1, monthly_budget_usd=10.0)  # should not raise
