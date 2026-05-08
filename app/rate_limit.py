"""Tiny in-memory rate limiter — token-bucket per (key, scope).

Good enough for /login and /forgot brute-force defense on a single instance.
For multi-instance deployments swap with a Redis-backed limiter.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last: float


class TokenBucket:
    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self.capacity = capacity
        self.refill = refill_per_second
        self._buckets: dict[str, _Bucket] = defaultdict(lambda: _Bucket(capacity, time.monotonic()))
        self._lock = threading.Lock()

    def take(self, key: str, cost: float = 1.0) -> bool:
        now = time.monotonic()
        with self._lock:
            b = self._buckets[key]
            elapsed = now - b.last
            b.tokens = min(self.capacity, b.tokens + elapsed * self.refill)
            b.last = now
            if b.tokens >= cost:
                b.tokens -= cost
                return True
            return False


# 10 attempts per 5 min ≈ refill 10/300s
login_limiter = TokenBucket(capacity=10, refill_per_second=10 / 300)
# 5 reset/signup mails per 10 min per email/IP
mail_limiter = TokenBucket(capacity=5, refill_per_second=5 / 600)
