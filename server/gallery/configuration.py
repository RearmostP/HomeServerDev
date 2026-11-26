"""Load and validate settings used when the server starts."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from gallery.services.storage import default_storage_root


@dataclass(frozen=True)
class Settings:
    server_directory: Path
    browser_directory: Path
    storage_root: Path
    opaque_setup: str
    local_http: bool
    origin: str
    tailscale_enabled: bool

    # Performance tuning (with sensible defaults)
    max_upload_mb: int = 26
    session_hours: int = 12
    auth_rate_limit_requests: int = 30
    auth_rate_limit_window_seconds: int = 60
    auth_rate_limit_max_keys: int = 10000
    session_cache_max_size: int = 1000
    session_cache_ttl_seconds: int = 300
    opaque_timeout_seconds: float = 15.0
    opaque_circuit_breaker_threshold: int = 5
    opaque_circuit_breaker_timeout: float = 30.0
    db_pool_size: int = 10
    db_busy_timeout_ms: int = 5000
    db_cache_size_mb: int = 32
    db_mmap_size_mb: int = 256

    @classmethod
    def from_environment(cls, storage_root: Path | None = None) -> "Settings":
        server_directory = Path(__file__).resolve().parent.parent
        opaque_setup = os.environ.get("OPAQUE_SERVER_SETUP")
        if not opaque_setup:
            raise RuntimeError("Set OPAQUE_SERVER_SETUP before starting the server.")

        local_http = os.environ.get("GALLERY_LOCAL_HTTP") == "1"
        origin = os.environ.get(
            "GALLERY_ORIGIN", "http://localhost:8000" if local_http else ""
        )
        if not origin or not origin.startswith(("https://", "http://localhost:")):
            raise RuntimeError("Set GALLERY_ORIGIN to the exact HTTPS origin.")

        selected_storage_root = (
            Path(storage_root)
            if storage_root is not None
            else default_storage_root()
        )

        # Parse optional performance settings from environment
        def parse_int(env_key: str, default: int) -> int:
            val = os.environ.get(env_key)
            return int(val) if val and val.isdigit() else default

        def parse_float(env_key: str, default: float) -> float:
            val = os.environ.get(env_key)
            try:
                return float(val) if val else default
            except ValueError:
                return default

        return cls(
            server_directory=server_directory,
            browser_directory=server_directory.parent / "clients" / "browser",
            storage_root=selected_storage_root,
            opaque_setup=opaque_setup,
            local_http=local_http,
            origin=origin,
            tailscale_enabled=os.environ.get("GALLERY_TAILSCALE_ROLE") == "1",
            # Performance settings
            max_upload_mb=parse_int("GALLERY_MAX_UPLOAD_MB", 26),
            session_hours=parse_int("GALLERY_SESSION_HOURS", 12),
            auth_rate_limit_requests=parse_int("GALLERY_AUTH_RATE_LIMIT", 30),
            auth_rate_limit_window_seconds=parse_int("GALLERY_AUTH_RATE_WINDOW", 60),
            auth_rate_limit_max_keys=parse_int("GALLERY_AUTH_RATE_MAX_KEYS", 10000),
            session_cache_max_size=parse_int("GALLERY_SESSION_CACHE_SIZE", 1000),
            session_cache_ttl_seconds=parse_int("GALLERY_SESSION_CACHE_TTL", 300),
            opaque_timeout_seconds=parse_float("GALLERY_OPAQUE_TIMEOUT", 15.0),
            opaque_circuit_breaker_threshold=parse_int("GALLERY_OPAQUE_CB_THRESHOLD", 5),
            opaque_circuit_breaker_timeout=parse_float("GALLERY_OPAQUE_CB_TIMEOUT", 30.0),
            db_pool_size=parse_int("GALLERY_DB_POOL_SIZE", 10),
            db_busy_timeout_ms=parse_int("GALLERY_DB_BUSY_TIMEOUT", 5000),
            db_cache_size_mb=parse_int("GALLERY_DB_CACHE_MB", 32),
            db_mmap_size_mb=parse_int("GALLERY_DB_MMAP_MB", 256),
        )

    def tailscale_origin_host(self) -> str:
        if self.local_http:
            raise RuntimeError("Tailscale mode requires the HTTPS gallery origin.")

        origin = urlsplit(self.origin)
        host = origin.hostname
        if (
            origin.scheme != "https"
            or not host
            or origin.netloc.casefold() != host.casefold()
            or origin.path
            or origin.query
            or origin.fragment
            or not host.casefold().endswith(".ts.net")
        ):
            raise RuntimeError(
                "Tailscale mode requires GALLERY_ORIGIN to be the HTTPS .ts.net origin without a path or port."
            )
        return host

    @property
    def max_request_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def session_seconds(self) -> int:
        return self.session_hours * 3600