"""Handle registration, login challenges, and session creation."""

import re
import secrets
import sqlite3
import time

from flask import Blueprint, abort, jsonify, request

from gallery.configuration import Settings
from gallery.services.database import Database
from gallery.services.opaque import run_opaque_operation
from gallery.services.photo_storage import PhotoStorage
from gallery.services.rate_limiter import get_auth_rate_limiter
from gallery.services.request_utils import json_body, required_field, token_digest
from gallery.services.session_cache import get_session_cache
from gallery.services.username import validate_username


def create_authentication_blueprint(
    database: Database, photo_storage: PhotoStorage, settings: Settings
) -> Blueprint:
    routes = Blueprint("authentication", __name__)
    rate_limiter = get_auth_rate_limiter(
        max_requests=settings.auth_rate_limit_requests,
        window_seconds=settings.auth_rate_limit_window_seconds,
        max_keys=settings.auth_rate_limit_max_keys,
    )
    session_cache = get_session_cache(
        database,
        max_size=settings.session_cache_max_size,
        ttl_seconds=settings.session_cache_ttl_seconds,
    )

    def start_challenge(username: str, kind: str, state: str) -> str:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with database.connection(write=True) as connection:
            connection.execute("DELETE FROM challenges WHERE expires <= ?", (now,))
            connection.execute(
                "INSERT INTO challenges VALUES (?, ?, ?, ?, ?)",
                (token_digest(token), username, kind, state, now + 180),
            )
        return token

    def consume_challenge(data: dict, expected_kind: str):
        challenge_id = token_digest(required_field(data, "challenge", 64))
        with database.connection(write=True) as connection:
            challenge = connection.execute(
                "SELECT * FROM challenges WHERE id = ?", (challenge_id,)
            ).fetchone()
            connection.execute("DELETE FROM challenges WHERE id = ?", (challenge_id,))
        if (
            challenge is None
            or challenge["kind"] != expected_kind
            or challenge["expires"] <= time.time()
        ):
            abort(401)
        return challenge

    def apply_rate_limit() -> None:
        address = (
            request.headers.get("Tailscale-User-Login")
            or request.remote_addr
            or "local"
        )
        if not rate_limiter.check_limit(address):
            abort(429)

    @routes.post("/api/auth/register/start")
    def register_start():
        apply_rate_limit()
        data = json_body()
        username = validate_username(data.get("username"))
        email = required_field(data, "email", 254).strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            abort(400, "כתובת מייל לא תקינה")
        result = run_opaque_operation(
            settings,
            "register",
            userIdentifier=username,
            registrationRequest=required_field(data, "registrationRequest"),
        )
        return {
            **result,
            "challenge": start_challenge(username, "register", email),
        }

    @routes.post("/api/auth/register/finish")
    def register_finish():
        data = json_body()
        challenge = consume_challenge(data, "register")
        username = challenge["username"]
        record = required_field(data, "registrationRecord")
        run_opaque_operation(
            settings,
            "checkRecord",
            userIdentifier=username,
            registrationRecord=record,
        )
        try:
            with database.connection(write=True) as connection:
                connection.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                    (
                        username,
                        challenge["state"],
                        record,
                        required_field(data, "publicKey"),
                        required_field(data, "privateKey"),
                    ),
                )
                connection.execute(
                    "INSERT INTO albums VALUES (?, 1, ?)", (username, "גלריה")
                )
                connection.execute(
                    "INSERT INTO access VALUES (?, 1, ?, ?)",
                    (username, username, required_field(data, "albumKey")),
                )
                photo_storage.create_album_directory(username, 1)
        except sqlite3.IntegrityError:
            abort(409, "שם המשתמש או המייל כבר קיימים")
        return {"ok": True}, 201

    @routes.post("/api/auth/login/start")
    def login_start():
        apply_rate_limit()
        data = json_body()
        username = validate_username(data.get("username"))
        with database.connection() as connection:
            account = connection.execute(
                "SELECT record FROM users WHERE username = ?", (username,)
            ).fetchone()
        result = run_opaque_operation(
            settings,
            "login",
            userIdentifier=username,
            registrationRecord=account["record"] if account else None,
            startLoginRequest=required_field(data, "startLoginRequest"),
        )
        state = result.pop("serverLoginState")
        return {
            **result,
            "challenge": start_challenge(username, "login", state),
        }

    @routes.post("/api/auth/login/finish")
    def login_finish():
        data = json_body()
        challenge = consume_challenge(data, "login")
        run_opaque_operation(
            settings,
            "finish",
            serverLoginState=challenge["state"],
            finishLoginRequest=required_field(data, "finishLoginRequest"),
        )
        username = challenge["username"]
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        session_seconds = settings.session_seconds
        with database.connection(write=True) as connection:
            account = connection.execute(
                "SELECT private_key FROM users WHERE username = ?", (username,)
            ).fetchone()
            if not account:
                abort(401)
            existing_device = connection.execute(
                "SELECT id FROM devices WHERE id = ? AND username = ?",
                (request.cookies.get("gallery_device"), username),
            ).fetchone()
            device_id = (
                existing_device["id"] if existing_device else secrets.token_urlsafe(32)
            )
            label = required_field(data, "device", 120)
            connection.execute(
                """INSERT INTO devices VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                   seen=excluded.seen, label=excluded.label""",
                (device_id, username, label, now),
            )
            connection.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (token_digest(token), device_id, now + session_seconds),
            )

        # Cache the new session
        session_cache.set(token, username, device_id, now + session_seconds)

        response = jsonify(privateKey=account["private_key"], username=username)
        response.set_cookie(
            "gallery_session",
            token,
            max_age=session_seconds,
            secure=not settings.local_http,
            httponly=True,
            samesite="Strict",
        )
        response.set_cookie(
            "gallery_device",
            device_id,
            max_age=365 * 86400,
            secure=not settings.local_http,
            httponly=True,
            samesite="Strict",
        )
        return response

    return routes