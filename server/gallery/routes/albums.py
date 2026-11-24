"""Handle album listing, creation, sharing, and deletion."""

from flask import Blueprint, abort, g

from gallery.services.authorization import require_album_access
from gallery.services.database import Database
from gallery.services.photo_storage import PhotoStorage
from gallery.services.request_utils import json_body, required_field
from gallery.services.username import validate_username


def create_album_blueprint(
    database: Database, photo_storage: PhotoStorage
) -> Blueprint:
    routes = Blueprint("albums", __name__)

    @routes.get("/api/albums")
    def list_albums():
        username = g.account["username"]
        with database.connection() as connection:
            rows = connection.execute(
                """
                SELECT albums.*, wrapped_key,
                    (SELECT count(*) FROM photos
                     WHERE photos.owner=albums.owner AND photos.number=albums.number) AS count,
                    (SELECT count(*) FROM access AS peers
                     WHERE peers.owner=albums.owner AND peers.number=albums.number
                       AND peers.username<>albums.owner) AS shared
                FROM albums JOIN access USING(owner, number)
                WHERE access.username=?
                ORDER BY albums.owner<>?, albums.number, albums.owner
                """,
                (username, username),
            )
            album_list = [dict(row) for row in rows]
        return {"albums": album_list}

    @routes.post("/api/albums")
    def create_album():
        data = json_body()
        owner = g.account["username"]
        with database.connection(write=True) as connection:
            used_numbers = {
                row[0]
                for row in connection.execute(
                    "SELECT number FROM albums WHERE owner=?", (owner,)
                )
            }
            number = None
            for candidate in range(2, 49):
                if candidate not in used_numbers:
                    number = candidate
                    break
            if number is None:
                abort(409, "ניתן ליצור עד 48 אלבומים כולל הגלריה")

            name = required_field(data, "name", 80).strip()
            if not name:
                abort(400)
            connection.execute(
                "INSERT INTO albums VALUES (?, ?, ?)", (owner, number, name)
            )
            connection.execute(
                "INSERT INTO access VALUES (?, ?, ?, ?)",
                (owner, number, owner, required_field(data, "albumKey")),
            )
            photo_storage.create_album_directory(owner, number)
        return {"number": number}, 201

    @routes.post("/api/albums/<int:number>/delete")
    def delete_album(number: int):
        if number == 1:
            abort(403, "אי אפשר למחוק את הגלריה")

        owner = g.account["username"]
        with database.connection(write=True) as connection:
            require_album_access(connection, owner, number, g.account["username"])
            images = connection.execute(
                "SELECT id FROM photos WHERE owner=? AND number=?",
                (owner, number),
            ).fetchall()
            connection.execute(
                "DELETE FROM photos WHERE owner=? AND number=?", (owner, number)
            )
            connection.execute(
                "DELETE FROM access WHERE owner=? AND number=?", (owner, number)
            )
            connection.execute(
                "DELETE FROM albums WHERE owner=? AND number=?", (owner, number)
            )

        for image in images:
            photo_storage.photo_file(owner, number, image["id"]).unlink(
                missing_ok=True
            )
        return {"ok": True}

    @routes.get("/api/users/<username>/key")
    def public_key(username: str):
        username = validate_username(username)
        with database.connection() as connection:
            account = connection.execute(
                "SELECT public_key FROM users WHERE username=?", (username,)
            ).fetchone()
        if account is None:
            abort(404, "המשתמש לא נמצא")
        return {"publicKey": account["public_key"]}

    @routes.post("/api/albums/<int:number>/share")
    def share_album(number: int):
        data = json_body()
        owner = g.account["username"]
        recipient = validate_username(data.get("username"))
        if recipient == owner:
            abort(400)

        with database.connection(write=True) as connection:
            require_album_access(connection, owner, number, g.account["username"])
            recipient_exists = connection.execute(
                "SELECT 1 FROM users WHERE username=?", (recipient,)
            ).fetchone()
            if recipient_exists is None:
                abort(404)
            connection.execute(
                """INSERT INTO access VALUES (?, ?, ?, ?)
                   ON CONFLICT(owner, number, username)
                   DO UPDATE SET wrapped_key=excluded.wrapped_key""",
                (owner, number, recipient, required_field(data, "albumKey")),
            )
        return {"ok": True}

    return routes
