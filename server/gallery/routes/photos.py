"""Handle encrypted photo upload, listing, and download."""

import secrets
import time
from flask import abort

from flask import Blueprint, g, request, send_file

from gallery.services.authorization import require_album_access
from gallery.services.database import Database
from gallery.services.photo_storage import PhotoStorage
from gallery.services.request_utils import required_field


def create_photo_blueprint(
    database: Database, photo_storage: PhotoStorage
) -> Blueprint:
    routes = Blueprint("photos", __name__)

    @routes.get("/api/albums/<owner>/<int:number>/photos")
    def list_photos(owner: str, number: int):
        with database.connection() as connection:
            require_album_access(connection, owner, number, g.account["username"])
            rows = connection.execute(
                """SELECT id, metadata FROM photos
                   WHERE owner=? AND number=? ORDER BY uploaded DESC, id""",
                (owner, number),
            )
            photo_list = [dict(row) for row in rows]
        return {"photos": photo_list}

    @routes.post("/api/albums/<int:number>/photos")
    def upload_photo(number: int):
        owner = g.account["username"]
        content = request.files.get("ciphertext")
        metadata = required_field(request.form, "metadata")
        if content is None:
            abort(400)

        # Read content first (into memory - max 26MB per config)
        ciphertext = content.read()
        if len(ciphertext) < 17:
            abort(400)

        photo_id = secrets.token_hex(16)

        # Atomically write file with per-album lock
        try:
            path = photo_storage.upload_photo_atomic(owner, number, photo_id, ciphertext)
        except FileExistsError:
            abort(409, "Photo ID collision, please retry")

        try:
            with database.connection(write=True) as connection:
                album = connection.execute(
                    """SELECT wrapped_key FROM access
                       WHERE owner=? AND number=? AND username=?""",
                    (owner, number, owner),
                ).fetchone()
                if (
                    album is None
                    or album["wrapped_key"]
                    != required_field(request.form, "albumVersion")
                ):
                    abort(409, "האלבום השתנה")
                connection.execute(
                    "INSERT INTO photos VALUES (?, ?, ?, ?, ?)",
                    (photo_id, owner, number, metadata, int(time.time())),
                )
        except BaseException:
            # Clean up file on DB failure
            path.unlink(missing_ok=True)
            raise
        return {"id": photo_id}, 201

    @routes.get("/api/photos/<photo_id>")
    def download_photo(photo_id: str):
        with database.connection() as connection:
            photo = connection.execute(
                "SELECT owner, number FROM photos WHERE id=?", (photo_id,)
            ).fetchone()
            if photo is None:
                abort(404)
            require_album_access(
                connection,
                photo["owner"],
                photo["number"],
                g.account["username"],
            )

        path = photo_storage.photo_file(photo["owner"], photo["number"], photo_id)
        return send_file(path, mimetype="application/octet-stream", as_attachment=True)

    return routes