"""Validate usernames against the gallery's existing naming rules."""

import re

from flask import abort


USERNAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,23}")
WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "com1",
        "com2",
        "com3",
        "com4",
        "com5",
        "com6",
        "com7",
        "com8",
        "com9",
        "lpt1",
        "lpt2",
        "lpt3",
        "lpt4",
        "lpt5",
        "lpt6",
        "lpt7",
        "lpt8",
        "lpt9",
    }
)


def validate_username(value: object) -> str:
    if not isinstance(value, str) or not USERNAME_PATTERN.fullmatch(value):
        abort(
            400,
            "שם המשתמש חייב להכיל 3–24 תווים, להתחיל באות אנגלית, "
            "ולהכיל רק אותיות אנגליות, ספרות או קו תחתון. "
            "שמות התקנים השמורים של Windows אינם מותרים "
            "(CON, PRN, AUX, NUL, COM1–COM9 ו-LPT1–LPT9).",
        )
    # Check Windows-reserved device names case-insensitively
    if value.lower() in WINDOWS_RESERVED_DEVICE_NAMES:
        abort(
            400,
            "שם המשתמש חייב להכיל 3–24 תווים, להתחיל באות אנגלית, "
            "ולהכיל רק אותיות אנגליות, ספרות או קו תחתון. "
            "שמות התקנים השמורים של Windows אינם מותרים "
            "(CON, PRN, AUX, NUL, COM1–COM9 ו-LPT1–LPT9).",
        )
    return value


def is_username_taken_case_insensitive(database, username: str) -> bool:
    """Check if a username exists case-insensitively in the database."""
    with database.connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM users WHERE LOWER(username) = LOWER(?)", (username,)
        ).fetchone()
    return row is not None
