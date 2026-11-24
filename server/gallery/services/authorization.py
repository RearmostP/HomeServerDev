"""Apply the shared album-access rule for album and photo operations."""

from flask import abort


def require_album_access(connection, owner: str, number: int, username: str) -> None:
    permission = connection.execute(
        """SELECT 1 FROM access
           WHERE owner=? AND number=? AND username=?""",
        (owner, number, username),
    ).fetchone()
    if permission is None:
        abort(404)
