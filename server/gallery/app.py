"""Build the Flask application and install its shared HTTP behavior."""

import time

from flask import Flask, abort, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from gallery.configuration import Settings
from gallery.routes.account import create_account_blueprint
from gallery.routes.albums import create_album_blueprint
from gallery.routes.authentication import (
    create_authentication_blueprint,
    token_digest,
)
from gallery.routes.photos import create_photo_blueprint
from gallery.services.database import Database
from gallery.services.photo_storage import PhotoStorage
from gallery.services.storage import initialize_storage


MAX_REQUEST_BYTES = 26 * 1024 * 1024
API_ERROR_CODES = (400, 401, 403, 404, 409, 413, 415, 429, 503)


def create_app(settings: Settings | None = None) -> Flask:
    if settings is None:
        settings = Settings.from_environment()

    storage_root = initialize_storage(settings.storage_root)
    database = Database(storage_root)
    database.initialize()
    photo_storage = PhotoStorage(storage_root)

    application = Flask(__name__, static_folder=None)
    application.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    application.extensions["gallery_database"] = database
    application.extensions["gallery_photo_storage"] = photo_storage

    @application.before_request
    def protect_requests():
        if (
            request.method == "POST"
            and request.headers.get("Origin") != settings.origin
        ):
            abort(403)
        if request.path.startswith("/api/") and not request.path.startswith(
            "/api/auth/"
        ):
            token = request.cookies.get("gallery_session")
            if not token:
                abort(401)
            with database.connection() as connection:
                account = connection.execute(
                    """SELECT username, device FROM sessions
                       JOIN devices ON device = id
                       WHERE token = ? AND expires > ?""",
                    (token_digest(token), int(time.time())),
                ).fetchone()
            if account is None:
                abort(401)
            g.account = account

    @application.after_request
    def add_security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; "
            "img-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    def api_error(error: HTTPException):
        return jsonify(error=error.description), error.code

    for status_code in API_ERROR_CODES:
        application.register_error_handler(status_code, api_error)

    @application.get("/")
    def index():
        return send_file(settings.browser_directory / "index.html")

    @application.get("/app.css")
    def stylesheet():
        return send_file(settings.browser_directory / "app.css")

    @application.get("/app.js")
    def javascript():
        return send_file(settings.browser_directory / "dist" / "app.js")

    application.register_blueprint(
        create_authentication_blueprint(database, photo_storage, settings)
    )
    application.register_blueprint(create_account_blueprint(database, settings))
    application.register_blueprint(
        create_album_blueprint(database, photo_storage)
    )
    application.register_blueprint(create_photo_blueprint(database, photo_storage))
    return application
