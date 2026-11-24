import hashlib
import json
import os
import re
import secrets
import sqlite3
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, g, jsonify, request, send_file

from storage import initialize_storage

SERVER = Path(__file__).resolve().parent
BROWSER = SERVER.parent / "clients" / "browser"
ROOT = initialize_storage()
APP = Flask(__name__, static_folder=None)
APP.config["MAX_CONTENT_LENGTH"] = 26 * 1024 * 1024
SESSION_SECONDS = 12 * 3600
USERNAME = re.compile(r"[a-z][a-z0-9_]{2,23}")
RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}
SETUP = os.environ.get("OPAQUE_SERVER_SETUP")
if not SETUP:
    raise RuntimeError("Set OPAQUE_SERVER_SETUP before starting the server.")


@contextmanager
def database(write=False):
    connection = sqlite3.connect(ROOT / "gallery.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
    finally:
        connection.close()


with database() as db:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, record TEXT NOT NULL,
        public_key TEXT NOT NULL, private_key TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS albums (
        owner TEXT REFERENCES users(username), number INTEGER CHECK(number BETWEEN 1 AND 48),
        name TEXT NOT NULL, PRIMARY KEY(owner, number)
    );
    CREATE TABLE IF NOT EXISTS access (
        owner TEXT, number INTEGER, username TEXT REFERENCES users(username),
        wrapped_key TEXT NOT NULL, PRIMARY KEY(owner, number, username),
        FOREIGN KEY(owner, number) REFERENCES albums(owner, number)
    );
    CREATE TABLE IF NOT EXISTS photos (
        id TEXT PRIMARY KEY, owner TEXT, number INTEGER, metadata TEXT NOT NULL,
        uploaded INTEGER NOT NULL, FOREIGN KEY(owner, number) REFERENCES albums(owner, number)
    );
    CREATE TABLE IF NOT EXISTS devices (
        id TEXT PRIMARY KEY, username TEXT REFERENCES users(username),
        label TEXT NOT NULL, seen INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY, device TEXT REFERENCES devices(id) ON DELETE CASCADE,
        expires INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS challenges (
        id TEXT PRIMARY KEY, username TEXT NOT NULL, kind TEXT NOT NULL,
        state TEXT NOT NULL, expires INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS auth_attempts (ip TEXT NOT NULL, attempted INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS auth_attempts_time ON auth_attempts(attempted);
    """)


def body():
    value = request.get_json()
    if not isinstance(value, dict):
        abort(400)
    return value


def field(data, name, limit=8192):
    value = data.get(name)
    if not isinstance(value, str) or not value or len(value) > limit:
        abort(400)
    return value


def user_name(value):
    if not isinstance(value, str) or not USERNAME.fullmatch(value) or value in RESERVED:
        abort(400, "שם משתמש לא תקין")
    return value


def opaque(operation, **data):
    result = subprocess.run(
        ["node", str(BROWSER / "opaque-server.mjs")],
        input=json.dumps({"operation": operation, **data}),
        capture_output=True, encoding="utf-8", timeout=15,
        env={**os.environ, "OPAQUE_SERVER_SETUP": SETUP},
    )
    if result.returncode:
        abort(503, "רכיב האימות אינו זמין")
    response = json.loads(result.stdout)
    if response is None:
        abort(401, "פרטי אימות שגויים")
    return response


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def token_cookie(name, value, seconds):
    response = jsonify(ok=True)
    response.set_cookie(name, value, max_age=seconds, secure=not LOCAL_HTTP,
                        httponly=True, samesite="Strict")
    return response


LOCAL_HTTP = os.environ.get("GALLERY_LOCAL_HTTP") == "1"
ORIGIN = os.environ.get(
    "GALLERY_ORIGIN", "http://localhost:8000" if LOCAL_HTTP else ""
)
if not ORIGIN or not ORIGIN.startswith(("https://", "http://localhost:")):
    raise RuntimeError("Set GALLERY_ORIGIN to the exact HTTPS origin.")


@APP.before_request
def protect():
    if request.method == "POST" and request.headers.get("Origin") != ORIGIN:
        abort(403)
    if request.path.startswith("/api/") and not request.path.startswith("/api/auth/"):
        token = request.cookies.get("gallery_session")
        if not token:
            abort(401)
        with database() as db:
            g.account = db.execute(
                """SELECT username, device FROM sessions JOIN devices ON device = id
                   WHERE token = ? AND expires > ?""", (digest(token), int(time.time()))
            ).fetchone()
        if g.account is None:
            abort(401)


@APP.after_request
def headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; "
        "img-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


@APP.errorhandler(400)
@APP.errorhandler(401)
@APP.errorhandler(403)
@APP.errorhandler(404)
@APP.errorhandler(409)
@APP.errorhandler(413)
@APP.errorhandler(415)
@APP.errorhandler(429)
@APP.errorhandler(503)
def error(exc):
    return jsonify(error=exc.description), exc.code


@APP.get("/")
def index():
    return send_file(BROWSER / "index.html")


@APP.get("/app.css")
def stylesheet():
    return send_file(BROWSER / "app.css")


@APP.get("/app.js")
def javascript():
    return send_file(BROWSER / "dist" / "app.js")


def start_challenge(username, kind, state):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with database(True) as db:
        db.execute("DELETE FROM challenges WHERE expires <= ?", (now,))
        db.execute("INSERT INTO challenges VALUES (?, ?, ?, ?, ?)",
                   (digest(token), username, kind, state, now + 180))
    return token


def take_challenge(data, kind):
    token = digest(field(data, "challenge", 64))
    with database(True) as db:
        row = db.execute("SELECT * FROM challenges WHERE id = ?", (token,)).fetchone()
        db.execute("DELETE FROM challenges WHERE id = ?", (token,))
    if row is None or row["kind"] != kind or row["expires"] <= time.time():
        abort(401)
    return row


def rate_limit():
    now = int(time.time())
    address = request.headers.get("Tailscale-User-Login") or request.remote_addr or "local"
    with database(True) as db:
        db.execute("DELETE FROM auth_attempts WHERE attempted <= ?", (now - 60,))
        if db.execute("SELECT count(*) FROM auth_attempts WHERE ip = ?", (address,)).fetchone()[0] >= 30:
            abort(429)
        db.execute("INSERT INTO auth_attempts VALUES (?, ?)", (address, now))


@APP.post("/api/auth/register/start")
def register_start():
    rate_limit()
    data = body()
    username = user_name(data.get("username"))
    email = field(data, "email", 254).strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        abort(400, "כתובת מייל לא תקינה")
    result = opaque("register", userIdentifier=username,
                    registrationRequest=field(data, "registrationRequest"))
    return {**result, "challenge": start_challenge(username, "register", email)}


@APP.post("/api/auth/register/finish")
def register_finish():
    data = body()
    row = take_challenge(data, "register")
    username = row["username"]
    record = field(data, "registrationRecord")
    opaque("checkRecord", userIdentifier=username, registrationRecord=record)
    try:
        with database(True) as db:
            db.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                       (username, row["state"], record, field(data, "publicKey"),
                        field(data, "privateKey")))
            db.execute("INSERT INTO albums VALUES (?, 1, ?)", (username, "גלריה"))
            db.execute("INSERT INTO access VALUES (?, 1, ?, ?)",
                       (username, username, field(data, "albumKey")))
            album_path(username, 1).mkdir(parents=True, exist_ok=True)
    except sqlite3.IntegrityError:
        abort(409, "שם המשתמש או המייל כבר קיימים")
    return {"ok": True}, 201


@APP.post("/api/auth/login/start")
def login_start():
    rate_limit()
    data = body()
    username = user_name(data.get("username"))
    with database() as db:
        account = db.execute("SELECT record FROM users WHERE username = ?", (username,)).fetchone()
    result = opaque("login", userIdentifier=username,
                    registrationRecord=account["record"] if account else None,
                    startLoginRequest=field(data, "startLoginRequest"))
    state = result.pop("serverLoginState")
    return {**result, "challenge": start_challenge(username, "login", state)}


@APP.post("/api/auth/login/finish")
def login_finish():
    data = body()
    row = take_challenge(data, "login")
    opaque("finish", serverLoginState=row["state"],
           finishLoginRequest=field(data, "finishLoginRequest"))
    username = row["username"]
    now = int(time.time())
    token = secrets.token_urlsafe(32)
    with database(True) as db:
        account = db.execute("SELECT private_key FROM users WHERE username = ?", (username,)).fetchone()
        if not account:
            abort(401)
        device = db.execute("SELECT id FROM devices WHERE id = ? AND username = ?",
                            (request.cookies.get("gallery_device"), username)).fetchone()
        device_id = device["id"] if device else secrets.token_urlsafe(32)
        label = field(data, "device", 120)
        db.execute("INSERT INTO devices VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET seen=excluded.seen, label=excluded.label",
                   (device_id, username, label, now))
        db.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
        db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (digest(token), device_id, now + SESSION_SECONDS))
    response = jsonify(privateKey=account["private_key"], username=username)
    for name, value, age in (("gallery_session", token, SESSION_SECONDS),
                              ("gallery_device", device_id, 365 * 86400)):
        response.set_cookie(name, value, max_age=age, secure=not LOCAL_HTTP,
                            httponly=True, samesite="Strict")
    return response


@APP.post("/api/logout")
def logout():
    with database(True) as db:
        db.execute("DELETE FROM sessions WHERE token = ?", (digest(request.cookies["gallery_session"]),))
    return token_cookie("gallery_session", "", 0)


@APP.get("/api/devices")
def devices():
    with database() as db:
        rows = db.execute("SELECT id, label, seen FROM devices WHERE username=? ORDER BY seen DESC",
                          (g.account["username"],))
        return {"devices": [dict(row, current=row["id"] == g.account["device"]) for row in rows]}


@APP.post("/api/devices/revoke")
def revoke_device():
    with database(True) as db:
        db.execute("DELETE FROM devices WHERE id=? AND username=?",
                   (field(body(), "id", 64), g.account["username"]))
    return {"ok": True}


def album_path(owner, number):
    return ROOT / owner / f"{number:03}"


def check_album(db, owner, number):
    if db.execute("SELECT 1 FROM access WHERE owner=? AND number=? AND username=?",
                  (owner, number, g.account["username"])).fetchone() is None:
        abort(404)


@APP.get("/api/albums")
def albums():
    with database() as db:
        rows = db.execute("""
            SELECT albums.*, wrapped_key,
                (SELECT count(*) FROM photos WHERE photos.owner=albums.owner AND photos.number=albums.number) AS count,
                (SELECT count(*) FROM access AS peers WHERE peers.owner=albums.owner AND peers.number=albums.number AND peers.username<>albums.owner) AS shared
            FROM albums JOIN access USING(owner, number)
            WHERE access.username=? ORDER BY albums.owner<>?, albums.number, albums.owner
        """, (g.account["username"], g.account["username"]))
        return {"albums": [dict(row) for row in rows]}


@APP.post("/api/albums")
def create_album():
    data = body()
    owner = g.account["username"]
    with database(True) as db:
        used = {row[0] for row in db.execute("SELECT number FROM albums WHERE owner=?", (owner,))}
        number = next((n for n in range(2, 49) if n not in used), None)
        if number is None:
            abort(409, "ניתן ליצור עד 48 אלבומים כולל הגלריה")
        name = field(data, "name", 80).strip()
        if not name:
            abort(400)
        db.execute("INSERT INTO albums VALUES (?, ?, ?)", (owner, number, name))
        db.execute("INSERT INTO access VALUES (?, ?, ?, ?)", (owner, number, owner, field(data, "albumKey")))
        album_path(owner, number).mkdir(parents=True, exist_ok=True)
    return {"number": number}, 201


@APP.post("/api/albums/<int:number>/delete")
def delete_album(number):
    if number == 1:
        abort(403, "אי אפשר למחוק את הגלריה")
    owner = g.account["username"]
    with database(True) as db:
        check_album(db, owner, number)
        images = db.execute("SELECT id FROM photos WHERE owner=? AND number=?", (owner, number)).fetchall()
        db.execute("DELETE FROM photos WHERE owner=? AND number=?", (owner, number))
        db.execute("DELETE FROM access WHERE owner=? AND number=?", (owner, number))
        db.execute("DELETE FROM albums WHERE owner=? AND number=?", (owner, number))
    for image in images:
        (album_path(owner, number) / (image["id"] + ".bin")).unlink(missing_ok=True)
    return {"ok": True}


@APP.get("/api/users/<username>/key")
def public_key(username):
    with database() as db:
        row = db.execute("SELECT public_key FROM users WHERE username=?", (user_name(username),)).fetchone()
        if row is None:
            abort(404, "המשתמש לא נמצא")
        return {"publicKey": row["public_key"]}


@APP.post("/api/albums/<int:number>/share")
def share_album(number):
    data = body()
    owner = g.account["username"]
    recipient = user_name(data.get("username"))
    if recipient == owner:
        abort(400)
    with database(True) as db:
        check_album(db, owner, number)
        if not db.execute("SELECT 1 FROM users WHERE username=?", (recipient,)).fetchone():
            abort(404)
        db.execute("""INSERT INTO access VALUES (?, ?, ?, ?)
            ON CONFLICT(owner, number, username) DO UPDATE SET wrapped_key=excluded.wrapped_key""",
                   (owner, number, recipient, field(data, "albumKey")))
    return {"ok": True}


@APP.get("/api/albums/<owner>/<int:number>/photos")
def photos(owner, number):
    with database() as db:
        check_album(db, owner, number)
        rows = db.execute("""SELECT id, metadata FROM photos WHERE owner=? AND number=?
                          ORDER BY uploaded DESC, id""", (owner, number))
        return {"photos": [dict(row) for row in rows]}


@APP.post("/api/albums/<int:number>/photos")
def upload(number):
    owner = g.account["username"]
    content = request.files.get("ciphertext")
    metadata = field(request.form, "metadata")
    if content is None:
        abort(400)
    photo_id = secrets.token_hex(16)
    path = album_path(owner, number) / (photo_id + ".bin")
    if not path.parent.is_dir():
        abort(404)
    with path.open("xb") as output:
        try:
            content.save(output)
            if output.tell() < 17:
                abort(400)
        except BaseException:
            output.close()
            path.unlink()
            raise
    try:
        with database(True) as db:
            row = db.execute("SELECT wrapped_key FROM access WHERE owner=? AND number=? AND username=?",
                             (owner, number, owner)).fetchone()
            if row is None or row["wrapped_key"] != field(request.form, "albumVersion"):
                abort(409, "האלבום השתנה")
            db.execute("INSERT INTO photos VALUES (?, ?, ?, ?, ?)",
                       (photo_id, owner, number, metadata, int(time.time())))
    except BaseException:
        path.unlink()
        raise
    return {"id": photo_id}, 201


@APP.get("/api/photos/<photo_id>")
def download(photo_id):
    with database() as db:
        row = db.execute("SELECT owner, number FROM photos WHERE id=?", (photo_id,)).fetchone()
        if row is None:
            abort(404)
        check_album(db, row["owner"], row["number"])
    return send_file(album_path(row["owner"], row["number"]) / (photo_id + ".bin"),
                     mimetype="application/octet-stream", as_attachment=True)


if __name__ == "__main__":
    from waitress import create_server

    gallery = create_server(
        APP,
        host="127.0.0.1",
        port=8000,
        max_request_body_size=26 * 1024 * 1024,
        clear_untrusted_proxy_headers=True,
    )
    tailscale = None
    try:
        if os.environ.get("GALLERY_TAILSCALE_ROLE") == "1":
            if LOCAL_HTTP:
                raise RuntimeError("Tailscale mode requires the HTTPS gallery origin.")
            origin = urlsplit(ORIGIN)
            host = origin.hostname
            if (
                origin.scheme != "https"
                or not host
                or origin.netloc.casefold() != host.casefold()
                or origin.path
                or origin.query
                or origin.fragment
                or not host.casefold().endswith(".ts.net")
            ):
                raise RuntimeError(
                    "Tailscale mode requires GALLERY_ORIGIN to be the HTTPS .ts.net origin without a path or port."
                )

            from roleforge import load

            tailscale = load(SERVER / "home-gallery.rfg").tailscale
            status = tailscale.connect()
            dns_name = str(status.get("dns_name", "")).rstrip(".")
            if status.get("state") != "Running" or dns_name.casefold() != host.casefold():
                raise RuntimeError(
                    "The RoleForge Tailscale node DNS name does not match GALLERY_ORIGIN."
                )
            status = tailscale.proxy.start()
            if (
                status.get("proxy_state") != "running"
                or status.get("listen_port") != 443
                or status.get("proxy_https") is not True
            ):
                raise RuntimeError("The RoleForge HTTPS proxy did not start on port 443.")

        gallery.run()
    finally:
        if tailscale is not None:
            tailscale.disconnect()
        gallery.close()
