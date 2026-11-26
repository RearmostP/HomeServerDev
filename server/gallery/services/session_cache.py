"""LRU cache with TTL for session token validation."""

import time
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Tuple

from gallery.services.database import Database
from gallery.services.request_utils import token_digest


@dataclass
class CachedSession:
    username: str
    device: str
    expires: int


class SessionCache:
    """Thread-safe LRU cache with TTL for session tokens."""

    def __init__(self, database: Database, max_size: int = 1000, ttl_seconds: int = 300):
        self.database = database
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, CachedSession] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, token: str) -> Optional[Tuple[str, str]]:
        """Get (username, device) for token if valid and cached."""
        token_hash = token_digest(token)
        now = int(time.time())

        with self._lock:
            # Periodic cleanup every 1000 calls
            if (self._hits + self._misses) % 1000 == 0:
                self._cleanup_expired_locked(now)

            cached = self._cache.get(token_hash)
            if cached is None:
                self._misses += 1
                return None

            if cached.expires <= now:
                # Expired
                del self._cache[token_hash]
                self._misses += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(token_hash)
            self._hits += 1
            return (cached.username, cached.device)

    def _cleanup_expired_locked(self, now: int) -> int:
        """Remove all expired entries. Must hold lock."""
        to_remove = [
            k for k, v in self._cache.items() if v.expires <= now
        ]
        for k in to_remove:
            del self._cache[k]
        return len(to_remove)

    def set(self, token: str, username: str, device: str, expires: int) -> None:
        """Cache a validated session."""
        token_hash = token_digest(token)
        with self._lock:
            # Remove if exists to update position
            if token_hash in self._cache:
                del self._cache[token_hash]
            elif len(self._cache) >= self.max_size:
                # Evict least recently used
                self._cache.popitem(last=False)

            self._cache[token_hash] = CachedSession(username, device, expires)

    def invalidate(self, token: str) -> None:
        """Remove a token from cache (e.g., on logout)."""
        token_hash = token_digest(token)
        with self._lock:
            self._cache.pop(token_hash, None)

    def invalidate_user(self, username: str) -> None:
        """Remove all sessions for a user (e.g., on password change)."""
        with self._lock:
            to_remove = [
                k for k, v in self._cache.items() if v.username == username
            ]
            for k in to_remove:
                del self._cache[k]

    def clear_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        now = int(time.time())
        with self._lock:
            return self._cleanup_expired_locked(now)

    def stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 3),
            }


# Global session cache
_session_cache: Optional[SessionCache] = None
_session_cache_lock = threading.Lock()


def get_session_cache(
    database: Database,
    max_size: int = 1000,
    ttl_seconds: int = 300,
) -> SessionCache:
    """Get or create the global session cache with configurable limits."""
    global _session_cache
    with _session_cache_lock:
        if _session_cache is None:
            _session_cache = SessionCache(database, max_size=max_size, ttl_seconds=ttl_seconds)
        return _session_cache