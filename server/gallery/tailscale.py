"""Connect the embedded RoleForge Tailscale node and HTTPS proxy."""

from contextlib import contextmanager

from gallery.configuration import Settings


@contextmanager
def tailscale_connection(settings: Settings):
    if not settings.tailscale_enabled:
        yield
        return

    host = settings.tailscale_origin_host()
    from roleforge import load

    tailscale = load(
        settings.server_directory / "home-gallery-host-settings.rfg"
    ).tailscale
    try:
        status = tailscale.connect()
        dns_name = str(status.get("dns_name", "")).rstrip(".")
        if (
            status.get("state") != "Running"
            or dns_name.casefold() != host.casefold()
        ):
            raise RuntimeError(
                "The RoleForge Tailscale node DNS name does not match GALLERY_ORIGIN."
            )

        status = tailscale.proxy.start()
        if (
            status.get("proxy_state") != "running"
            or status.get("listen_port") != 443
            or status.get("proxy_https") is not True
        ):
            raise RuntimeError(
                "The RoleForge HTTPS proxy did not start on port 443."
            )
        yield
    finally:
        tailscale.disconnect()
