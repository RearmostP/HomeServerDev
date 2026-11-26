"""Validate JSON and form fields and build standard API responses."""

import hashlib
from flask import abort, jsonify, request


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def json_body() -> dict:
    value = request.get_json()
    if not isinstance(value, dict):
        abort(400)
    return value


def required_field(data, name: str, limit: int = 8192) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value or len(value) > limit:
        abort(400)
    return value


def success_cookie(name: str, value: str, seconds: int, secure: bool):
    response = jsonify(ok=True)
    response.set_cookie(
        name,
        value,
        max_age=seconds,
        secure=secure,
        httponly=True,
        samesite="Strict",
    )
    return response