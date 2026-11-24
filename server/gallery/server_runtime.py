"""Start and close the local Waitress HTTP listener."""

from waitress import create_server

from gallery.configuration import Settings
from gallery.tailscale import tailscale_connection


def serve(application, settings: Settings) -> None:
    gallery = create_server(
        application,
        host="127.0.0.1",
        port=8000,
        max_request_body_size=26 * 1024 * 1024,
        clear_untrusted_proxy_headers=True,
    )
    try:
        with tailscale_connection(settings):
            gallery.run()
    finally:
        gallery.close()
