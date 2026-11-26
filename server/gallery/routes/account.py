"""Handle account devices, device revocation, and logout."""

from flask import Blueprint, g, request

from gallery.configuration import Settings
from gallery.services.database import Database
from gallery.services.request_utils import (
    json_body,
    required_field,
    success_cookie,
    token_digest,
)
from gallery.services.session_cache import get_session_cache


def create_account_blueprint(database: Database, settings: Settings) -> Blueprint:
    routes = Blueprint("account", __name__)
    session_cache = get_session_cache(database)

    @routes.post("/api/logout")
    def logout():
        token = request.cookies.get("gallery_session")
        if token:
            with database.connection(write=True) as connection:
                connection.execute(
                    "DELETE FROM sessions WHERE token = ?",
                    (token_digest(token),),
                )
            # Invalidate session cache
            session_cache.invalidate(token)
        return success_cookie(
            "gallery_session", "", 0, secure=not settings.local_http
        )

    @routes.get("/api/devices")
    def devices():
        with database.connection() as connection:
            rows = connection.execute(
                """SELECT id, label, seen FROM devices
                   WHERE username=? ORDER BY seen DESC""",
                (g.account["username"],),
            )
            device_list = [
                dict(row, current=row["id"] == g.account["device"]) for row in rows
            ]
        return {"devices": device_list}

    @routes.post("/api/devices/revoke")
    def revoke_device():
        data = json_body()
        device_id = required_field(data, "id", 64)
        username = g.account["username"]
        with database.connection(write=True) as connection:
            # Get sessions for this device to invalidate cache
            sessions = connection.execute(
                "SELECT token FROM sessions WHERE device = ?", (device_id,)
            ).fetchall()
            connection.execute(
                "DELETE FROM devices WHERE id=? AND username=?",
                (device_id, username),
            )
        # Invalidate all sessions for the revoked device
        for session in sessions:
            session_cache.invalidate(session["token"])
        return {"ok": True}

    return routes