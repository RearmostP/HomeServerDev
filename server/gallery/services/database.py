"""Open SQLite connections and create the server's existing schema."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
import logging

from gallery.configuration import Settings

logger = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, record TEXT NOT NULL,
    public_key TEXT NOT NULL, private_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS albums (
    owner TEXT REFERENCES users(username), number INTEGER CHECK(number BETWEEN 1 AND 48),
    name TEXT NOT NULL, PRIMARY KEY(owner, number)
);
CREATE TABLE IF NOT EXISTS access (
    owner TEXT, number INTEGER, username TEXT REFERENCES users(username),
    wrapped_key TEXT NOT NULL, PRIMARY KEY(owner, number, username),
    FOREIGN KEY(owner, number) REFERENCES albums(owner, number)
);
CREATE TABLE IF NOT EXISTS photos (
    id TEXT PRIMARY KEY, owner TEXT, number INTEGER, metadata TEXT NOT NULL,
    uploaded INTEGER NOT NULL, FOREIGN KEY(owner, number) REFERENCES albums(owner, number)
);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY, username TEXT REFERENCES users(username),
    label TEXT NOT NULL, seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY, device TEXT REFERENCES devices(id) ON DELETE CASCADE,
    expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS challenges (
    id TEXT PRIMARY KEY, username TEXT NOT NULL, kind TEXT NOT NULL,
    state TEXT NOT NULL, expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_attempts (ip TEXT NOT NULL, attempted INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS auth_attempts_time ON auth_attempts(attempted);
-- Performance indexes
CREATE INDEX IF NOT EXISTS sessions_expires ON sessions(expires);
CREATE INDEX IF NOT EXISTS sessions_token_expires ON sessions(token, expires);
CREATE INDEX IF NOT EXISTS devices_username ON devices(username);
CREATE INDEX IF NOT EXISTS devices_username_seen ON devices(username, seen DESC);
CREATE INDEX IF NOT EXISTS photos_owner_number_uploaded ON photos(owner, number, uploaded DESC, id);
CREATE INDEX IF NOT EXISTS access_username ON access(username);
CREATE INDEX IF NOT EXISTS access_owner_number ON access(owner, number);
CREATE INDEX IF NOT EXISTS photos_owner_number ON photos(owner, number);
CREATE INDEX IF NOT EXISTS challenges_expires ON challenges(expires);
-- Case-insensitive username uniqueness (ASCII usernames, NOCASE collation is correct)
CREATE UNIQUE INDEX IF NOT EXISTS users_username_nocase ON users(username COLLATE NOCASE);
"""


def _configure_connection(conn: sqlite3.Connection, settings: Settings) -> None:
    """Apply per-connection performance pragmas."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {settings.db_busy_timeout_ms}")
    conn.execute(f"PRAGMA cache_size = {-settings.db_cache_size_mb * 1024}")  # KB, negative = pages
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute(f"PRAGMA mmap_size = {settings.db_mmap_size_mb * 1024 * 1024}")


def _initialize_database_pragmas(conn: sqlite3.Connection) -> None:
    """Apply one-time database pragmas (WAL mode, etc.)."""
    conn.execute("PRAGMA journal_mode = WAL")


class Database:
    """Own the gallery SQLite file and provide transactional connections."""

    def __init__(self, storage_root: Path):
        self.path = storage_root / "gallery.sqlite3"
        self._settings: Settings | None = None
        self._pragmas_initialized = False

    def _get_settings(self) -> Settings:
        if self._settings is None:
            # Lazy load settings - will be set by app
            from gallery.configuration import Settings
            self._settings = Settings.from_environment(self.path.parent)
        return self._settings

    def set_settings(self, settings: Settings) -> None:
        """Set settings for connection configuration."""
        self._settings = settings

    def initialize(self) -> None:
        with self.connection() as connection:
            try:
                connection.executescript(SCHEMA)
            except sqlite3.IntegrityError as error:
                if str(error) == "UNIQUE constraint failed: users.username":
                    raise RuntimeError(
                        "Database contains usernames that differ only by letter case, "
                        "so the case-insensitive unique index cannot be created. "
                        "Resolve the conflicting usernames manually, then rerun the server."
                    ) from error
                raise
            # Initialize one-time pragmas (WAL mode)
            if not self._pragmas_initialized:
                _initialize_database_pragmas(connection)
                self._pragmas_initialized = True
                logger.info("Database initialized with WAL mode")

    @contextmanager
    def connection(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        """Get a new configured connection."""
        settings = self._get_settings()
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _configure_connection(conn, settings)
        try:
            with conn:
                if write:
                    conn.execute("BEGIN IMMEDIATE")
                yield conn
        finally:
            conn.close()

    def close(self) -> None:
        """No-op for compatibility (connections are closed per-request)."""
        pass
