"""In-memory rate limiter with sliding window and bounded memory."""

import time
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class RateLimitConfig:
    max_requests: int
    window_seconds: int


class RateLimiter:
    """Thread-safe in-memory rate limiter using sliding window with bounded memory."""

    def __init__(self, config: RateLimitConfig, max_keys: int = 10000):
        self.config = config
        self.max_keys = max_keys
        self._lock = threading.Lock()
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._last_access: Dict[str, float] = {}  # For LRU eviction
        self._cleanup_interval = 60  # seconds
        self._last_cleanup = time.time()

    def _cleanup_expired(self, now: float) -> None:
        """Remove expired entries."""
        if now - self._last_cleanup < self._cleanup_interval:
            return
        cutoff = now - self.config.window_seconds
        for key in list(self._requests.keys()):
            # Remove old timestamps
            self._requests[key] = [t for t in self._requests[key] if t > cutoff]
            if not self._requests[key]:
                del self._requests[key]
                self._last_access.pop(key, None)
        self._last_cleanup = now

    def _evict_lru_if_needed(self, key: str, now: float) -> None:
        """Evict least recently used key if at capacity and key is new."""
        if key in self._requests:
            return
        if len(self._requests) >= self.max_keys:
            # Find LRU key
            lru_key = min(self._last_access.keys(), key=lambda k: self._last_access[k])
            del self._requests[lru_key]
            del self._last_access[lru_key]

    def check_limit(self, key: str) -> bool:
        """Check if key is within rate limit. Returns True if allowed."""
        now = time.time()
        with self._lock:
            self._cleanup_expired(now)
            self._evict_lru_if_needed(key, now)
            cutoff = now - self.config.window_seconds
            timestamps = self._requests[key]
            # Remove expired
            timestamps[:] = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self.config.max_requests:
                return False
            timestamps.append(now)
            self._last_access[key] = now
            return True

    def get_remaining(self, key: str) -> int:
        """Get remaining requests for key."""
        now = time.time()
        with self._lock:
            self._cleanup_expired(now)
            cutoff = now - self.config.window_seconds
            timestamps = self._requests.get(key, [])
            timestamps[:] = [t for t in timestamps if t > cutoff]
            return max(0, self.config.max_requests - len(timestamps))


# Global rate limiter for auth attempts
_auth_rate_limiter: RateLimiter | None = None
_auth_rate_limiter_lock = threading.Lock()


def get_auth_rate_limiter(
    max_requests: int = 30,
    window_seconds: int = 60,
    max_keys: int = 10000,
) -> RateLimiter:
    """Get the global auth rate limiter with configurable limits."""
    global _auth_rate_limiter
    with _auth_rate_limiter_lock:
        if _auth_rate_limiter is None:
            _auth_rate_limiter = RateLimiter(
                RateLimitConfig(max_requests=max_requests, window_seconds=window_seconds),
                max_keys=max_keys,
            )
        return _auth_rate_limiter