"""Resolve album directories and encrypted photo files in the existing layout."""

import threading
from pathlib import Path


class PhotoStorage:
    """Own the on-disk paths for album directories and encrypted photos."""

    def __init__(self, root: Path):
        self.root = root
        self._album_locks: dict[tuple[str, int], threading.Lock] = {}
        self._locks_lock = threading.Lock()

    def _get_album_lock(self, owner: str, number: int) -> threading.Lock:
        """Get or create a lock for the given album."""
        key = (owner, number)
        with self._locks_lock:
            if key not in self._album_locks:
                self._album_locks[key] = threading.Lock()
            return self._album_locks[key]

    def album_directory(self, owner: str, number: int) -> Path:
        return self.root / owner / f"{number:03}"

    def create_album_directory(self, owner: str, number: int) -> Path:
        directory = self.album_directory(owner, number)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def photo_file(self, owner: str, number: int, photo_id: str) -> Path:
        return self.album_directory(owner, number) / f"{photo_id}.bin"

    def upload_photo_atomic(self, owner: str, number: int, photo_id: str, content_bytes: bytes) -> Path:
        """
        Atomically write a photo file with per-album locking.
        Returns the path to the written file.
        """
        lock = self._get_album_lock(owner, number)
        with lock:
            directory = self.create_album_directory(owner, number)
            path = directory / f"{photo_id}.bin"
            # Use exclusive creation to prevent overwrites
            with path.open("xb") as f:
                f.write(content_bytes)
            return path