"""Validate usernames against the gallery's existing naming rules."""

import re

from flask import abort


USERNAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{2,23}")
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
    if (
        not isinstance(value, str)
        or not USERNAME_PATTERN.fullmatch(value)
        or value in WINDOWS_RESERVED_DEVICE_NAMES
    ):
        abort(400, "שם משתמש לא תקין")
    return value
