"""Select and initialize the server's storage directory."""

import sys
from pathlib import Path


def default_storage_root() -> Path:
    if sys.platform == "win32":
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "server-storage"
        return Path(__file__).resolve().parents[2] / "server-storage"
    if sys.platform.startswith("linux"):
        return Path("/server-storage")
    raise RuntimeError(f"Unsupported server platform: {sys.platform}")


def initialize_storage(root: Path | None = None) -> Path:
    """Create the storage root after startup is explicitly requested."""
    storage_root = Path(root) if root is not None else default_storage_root()
    storage_root.mkdir(parents=True, exist_ok=True)
    return storage_root
