"""Token-bucket rate limiter per provider (MODEL-001).

Application-level singleton. max_per_min=0 means disabled (always allow).
Never waits forever — max_wait_sec timeout.
"""
from __future__ import annotations

import logging
import os
import threading
import time

log = logging.getLogger("hephaestus.core.rate_limit")


class RateLimiter:
    def __init__(self, *, max_per_min: int, max_wait_sec: float) -> None:
        self._max_per_min = max_per_min
        self._max_wait_sec = max_wait_sec
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def acquire(self, provider: str) -> bool:
        if self._max_per_min <= 0:
            return True
        bucket = self._get_bucket(provider)
        return bucket.acquire(self._max_per_min, self._max_wait_sec)

    def _get_bucket(self, provider: str) -> _Bucket:
        with self._lock:
            if provider not in self._buckets:
                self._buckets[provider] = _Bucket()
            return self._buckets[provider]


class _Bucket:
    def __init__(self) -> None:
        self._tokens: float = 0.0
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()
        self._initialized: bool = False

    def acquire(self, max_per_min: int, max_wait_sec: float) -> bool:
        with self._lock:
            self._refill(max_per_min)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            if max_wait_sec <= 0:
                return False
        deadline = time.monotonic() + max_wait_sec
        interval = 60.0 / max(max_per_min, 1)
        while time.monotonic() < deadline:
            time.sleep(min(0.1, interval / 2))
            with self._lock:
                self._refill(max_per_min)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
        return False

    def _refill(self, max_per_min: int) -> None:
        now = time.monotonic()
        if not self._initialized:
            self._tokens = float(max_per_min)
            self._initialized = True
        else:
            elapsed = now - self._last_refill
            refill = elapsed * (max_per_min / 60.0)
            self._tokens = min(float(max_per_min), self._tokens + refill)
        self._last_refill = now


_instance: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _instance
    if _instance is None:
        max_per_min = int(os.environ.get("HEPHAESTUS_RATE_LIMIT_PER_MIN", "0") or 0)
        max_wait_sec = float(os.environ.get("HEPHAESTUS_RATE_LIMIT_MAX_WAIT_SEC", "5") or 5)
        _instance = RateLimiter(max_per_min=max_per_min, max_wait_sec=max_wait_sec)
    return _instance
