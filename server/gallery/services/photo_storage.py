"""Resolve album directories and encrypted photo files in the existing layout."""

from pathlib import Path


class PhotoStorage:
    """Own the on-disk paths for album directories and encrypted photos."""

    def __init__(self, root: Path):
        self.root = root

    def album_directory(self, owner: str, number: int) -> Path:
        return self.root / owner / f"{number:03}"

    def create_album_directory(self, owner: str, number: int) -> Path:
        directory = self.album_directory(owner, number)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def photo_file(self, owner: str, number: int, photo_id: str) -> Path:
        return self.album_directory(owner, number) / f"{photo_id}.bin"
