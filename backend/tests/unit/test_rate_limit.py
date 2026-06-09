"""Unit tests for token-bucket rate limiter (MODEL-001)."""
from app.core.rate_limit import RateLimiter, get_rate_limiter


class TestTokenBucket:
    def test_allows_up_to_limit(self):
        rl = RateLimiter(max_per_min=5, max_wait_sec=0)
        for _ in range(5):
            assert rl.acquire("test") is True

    def test_rejects_over_limit_no_wait(self):
        rl = RateLimiter(max_per_min=2, max_wait_sec=0)
        assert rl.acquire("test") is True
        assert rl.acquire("test") is True
        assert rl.acquire("test") is False

    def test_max_wait_timeout(self):
        rl = RateLimiter(max_per_min=1, max_wait_sec=0.1)
        assert rl.acquire("test") is True
        assert rl.acquire("test") is False

    def test_disabled_is_noop(self):
        rl = RateLimiter(max_per_min=0, max_wait_sec=0)
        for _ in range(100):
            assert rl.acquire("test") is True

    def test_different_providers_independent(self):
        rl = RateLimiter(max_per_min=1, max_wait_sec=0)
        assert rl.acquire("a") is True
        assert rl.acquire("b") is True
        assert rl.acquire("a") is False

    def test_singleton(self):
        assert get_rate_limiter() is get_rate_limiter()
