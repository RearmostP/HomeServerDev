"""Handle account devices, device revocation, and logout."""

from flask import Blueprint, g, request

from gallery.configuration import Settings
from gallery.routes.authentication import token_digest
from gallery.services.database import Database
from gallery.services.request_utils import (
    json_body,
    required_field,
    success_cookie,
)


def create_account_blueprint(database: Database, settings: Settings) -> Blueprint:
    routes = Blueprint("account", __name__)

    @routes.post("/api/logout")
    def logout():
        with database.connection(write=True) as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token = ?",
                (token_digest(request.cookies["gallery_session"]),),
            )
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
        with database.connection(write=True) as connection:
            connection.execute(
                "DELETE FROM devices WHERE id=? AND username=?",
                (required_field(data, "id", 64), g.account["username"]),
            )
        return {"ok": True}

    return routes
