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
        return cls(
            server_directory=server_directory,
            browser_directory=server_directory.parent / "clients" / "browser",
            storage_root=selected_storage_root,
            opaque_setup=opaque_setup,
            local_http=local_http,
            origin=origin,
            tailscale_enabled=os.environ.get("GALLERY_TAILSCALE_ROLE") == "1",
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
