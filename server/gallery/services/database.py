"""Open SQLite connections and create the server's existing schema."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


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
"""


class Database:
    """Own the gallery SQLite file and provide transactional connections."""

    def __init__(self, storage_root: Path):
        self.path = storage_root / "gallery.sqlite3"

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connection(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                if write:
                    connection.execute("BEGIN IMMEDIATE")
                yield connection
        finally:
            connection.close()
