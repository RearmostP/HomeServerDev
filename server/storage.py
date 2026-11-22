"""Select and initialize the server's storage directory at startup."""

import sys
from pathlib import Path


def initialize_storage() -> Path:
    """Create the storage root and return its absolute path."""
    if sys.platform == "win32":
        launch_file = sys.executable if getattr(sys, "frozen", False) else __file__
        root = Path(launch_file).resolve().parent / "server-storage"
    elif sys.platform.startswith("linux"):
        root = Path("/server-storage")
    else:
        raise RuntimeError(f"Unsupported server platform: {sys.platform}")

    root.mkdir(parents=True, exist_ok=True)
    return root
