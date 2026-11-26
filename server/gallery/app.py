"""Build the Flask application and install its shared HTTP behavior."""

import logging
import os
import time

from flask import Flask, abort, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from gallery.configuration import Settings
from gallery.routes.account import create_account_blueprint
from gallery.routes.albums import create_album_blueprint
from gallery.routes.authentication import create_authentication_blueprint
from gallery.services.logging_config import RequestLogger, setup_logging
from gallery.services.request_utils import token_digest
from gallery.routes.photos import create_photo_blueprint
from gallery.services.database import Database
from gallery.services.photo_storage import PhotoStorage
from gallery.services.session_cache import get_session_cache
from gallery.services.storage import initialize_storage


API_ERROR_CODES = (400, 401, 403, 404, 409, 413, 415, 429, 503)


def create_app(settings: Settings | None = None) -> Flask:
    if settings is None:
        settings = Settings.from_environment()

    # Configure structured logging
    json_logs = os.environ.get("GALLERY_JSON_LOGS") == "1"
    log_level = getattr(logging, os.environ.get("GALLERY_LOG_LEVEL", "INFO").upper(), logging.INFO)
    setup_logging(json_format=json_logs, level=log_level)

    storage_root = initialize_storage(settings.storage_root)
    database = Database(storage_root)
    database.set_settings(settings)
    database.initialize()
    photo_storage = PhotoStorage(storage_root)
    session_cache = get_session_cache(database, max_size=settings.session_cache_max_size, ttl_seconds=settings.session_cache_ttl_seconds)

    # Static files served manually for backward compatibility with test baseline
    # In production, use reverse proxy (nginx) for static file serving
    application = Flask(__name__, static_folder=None)
    application.config["MAX_CONTENT_LENGTH"] = settings.max_request_bytes
    application.extensions["gallery_database"] = database
    application.extensions["gallery_photo_storage"] = photo_storage

    # Wrap with request logging middleware
    application.wsgi_app = RequestLogger(application.wsgi_app)

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

            # Fast path: check session cache first
            cached = session_cache.get(token)
            if cached:
                g.account = {"username": cached[0], "device": cached[1]}
                return

            # Fallback: validate against database
            with database.connection() as connection:
                account = connection.execute(
                    """SELECT username, device, expires FROM sessions
                       JOIN devices ON device = id
                       WHERE token = ? AND expires > ?""",
                    (token_digest(token), int(time.time())),
                ).fetchone()
            if account is None:
                abort(401)

            # Cache the validated session
            session_cache.set(token, account["username"], account["device"], account["expires"])
            g.account = {"username": account["username"], "device": account["device"]}

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

    # Manual routes for static files (test baseline compatibility)
    @application.get("/")
    def index():
        return send_file(settings.browser_directory / "index.html")

    @application.get("/app.css")
    def stylesheet():
        return send_file(settings.browser_directory / "app.css")

    @application.get("/app.js")
    def javascript():
        return send_file(settings.browser_directory / "dist" / "app.js")

    # Health check endpoint (no auth required)
    @application.get("/health")
    def health_check():
        """Health check endpoint for load balancers."""
        db_ok = False
        try:
            with database.connection() as conn:
                conn.execute("SELECT 1").fetchone()
            db_ok = True
        except Exception:
            pass

        cache_stats = session_cache.stats()

        return jsonify(
            status="healthy" if db_ok else "degraded",
            database="ok" if db_ok else "error",
            session_cache=cache_stats,
            timestamp=int(time.time()),
        )

    # Metrics endpoint (no auth required, but could be protected in production)
    @application.get("/metrics")
    def metrics():
        """Prometheus-compatible metrics endpoint."""
        cache_stats = session_cache.stats()
        lines = [
            "# HELP gallery_session_cache_hits Total cache hits",
            "# TYPE gallery_session_cache_hits counter",
            f"gallery_session_cache_hits {cache_stats['hits']}",
            "# HELP gallery_session_cache_misses Total cache misses",
            "# TYPE gallery_session_cache_misses counter",
            f"gallery_session_cache_misses {cache_stats['misses']}",
            "# HELP gallery_session_cache_hit_rate Cache hit rate",
            "# TYPE gallery_session_cache_hit_rate gauge",
            f"gallery_session_cache_hit_rate {cache_stats['hit_rate']}",
            "# HELP gallery_session_cache_size Current cache size",
            "# TYPE gallery_session_cache_size gauge",
            f"gallery_session_cache_size {cache_stats['size']}",
            "# HELP gallery_session_cache_max_size Maximum cache size",
            "# TYPE gallery_session_cache_max_size gauge",
            f"gallery_session_cache_max_size {cache_stats['max_size']}",
        ]
        return "\n".join(lines), 200, {"Content-Type": "text/plain; version=0.0.4"}

    application.register_blueprint(
        create_authentication_blueprint(database, photo_storage, settings)
    )
    application.register_blueprint(create_account_blueprint(database, settings))
    application.register_blueprint(
        create_album_blueprint(database, photo_storage)
    )
    application.register_blueprint(create_photo_blueprint(database, photo_storage))

    @application.teardown_appcontext
    def close_database(exception):
        database.close()

    return application
