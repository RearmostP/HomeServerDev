import io
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from dataclasses import replace
from types import ModuleType, SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVER_DIRECTORY.parent
sys.path.insert(0, str(SERVER_DIRECTORY))

import main
from gallery.app import create_app
from gallery.configuration import Settings
from gallery.server_runtime import serve
from gallery.services.database import Database
from gallery.services.storage import default_storage_root
from gallery.services.username import (
    WINDOWS_RESERVED_DEVICE_NAMES,
    is_username_taken_case_insensitive,
    validate_username,
)
from gallery.tailscale import tailscale_connection


BASELINE_ROUTES = {
    ("GET", "/"),
    ("GET", "/api/albums"),
    ("POST", "/api/albums"),
    ("POST", "/api/albums/<int:number>/delete"),
    ("POST", "/api/albums/<int:number>/photos"),
    ("POST", "/api/albums/<int:number>/share"),
    ("GET", "/api/albums/<owner>/<int:number>/photos"),
    ("POST", "/api/auth/login/finish"),
    ("POST", "/api/auth/login/start"),
    ("POST", "/api/auth/register/finish"),
    ("POST", "/api/auth/register/start"),
    ("GET", "/api/devices"),
    ("POST", "/api/devices/revoke"),
    ("POST", "/api/logout"),
    ("GET", "/api/photos/<photo_id>"),
    ("GET", "/api/users/<username>/key"),
    ("GET", "/app.css"),
    ("GET", "/app.js"),
    ("GET", "/health"),
    ("GET", "/metrics"),
}


def installer_server_files():
    installer = (REPOSITORY_ROOT / "install-server.sh").read_text(
        encoding="utf-8"
    )
    expected_copy_commands = (
        'cp "$repo"/server/main.py "$release/server/"',
        'cp -R "$repo"/server/gallery "$release/server/"',
    )
    for command in expected_copy_commands:
        if command not in installer:
            raise AssertionError(f"Installer is missing its server copy step: {command}")
    return [SERVER_DIRECTORY / "main.py", *SERVER_DIRECTORY.joinpath("gallery").rglob("*.py")]


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.storage_root = Path(self.temporary.name) / "server-storage"
        self.environment = patch.dict(
            os.environ,
            {
                "OPAQUE_SERVER_SETUP": "temporary-test-setup",
                "GALLERY_LOCAL_HTTP": "1",
                "GALLERY_TAILSCALE_ROLE": "",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop("GALLERY_ORIGIN", None)
        self.settings = Settings.from_environment(self.storage_root)
        self.application = create_app(self.settings)
        self.client = self.application.test_client()

    def post_json(self, path, body):
        return self.client.post(
            path, json=body, headers={"Origin": self.settings.origin}
        )

    def register_and_login(self, username="alice"):
        with patch(
            "gallery.routes.authentication.run_opaque_operation",
            side_effect=[
                {},
                {},
                {"serverLoginState": "login-state", "loginResponse": "response"},
                {},
            ],
        ):
            registration = self.post_json(
                "/api/auth/register/start",
                {
                    "username": username,
                    "email": f"{username}@example.com",
                    "registrationRequest": "registration-request",
                },
            )
            self.assertEqual(registration.status_code, 200)
            completed_registration = self.post_json(
                "/api/auth/register/finish",
                {
                    "challenge": registration.json["challenge"],
                    "registrationRecord": "registration-record",
                    "publicKey": "public-key",
                    "privateKey": "private-key",
                    "albumKey": "first-album-key",
                },
            )
            self.assertEqual(completed_registration.status_code, 201)

            login = self.post_json(
                "/api/auth/login/start",
                {"username": username, "startLoginRequest": "login-request"},
            )
            self.assertEqual(login.status_code, 200)
            completed_login = self.post_json(
                "/api/auth/login/finish",
                {
                    "challenge": login.json["challenge"],
                    "finishLoginRequest": "finish-login-request",
                    "device": "regression-test",
                },
            )
            self.assertEqual(completed_login.status_code, 200)
        return completed_login

    def test_api_routes_and_access_checks_match_baseline(self):
        routes = set()
        for rule in self.application.url_map.iter_rules():
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                routes.add((method, rule.rule))
        self.assertEqual(routes, BASELINE_ROUTES)
        self.assertEqual(self.client.get("/api/albums").status_code, 401)
        denied_post = self.client.post("/api/logout", headers={"Origin": "https://wrong"})
        self.assertEqual(denied_post.status_code, 403)

    def test_registration_login_album_and_encrypted_photo_round_trip(self):
        login = self.register_and_login()
        self.assertEqual(
            login.json, {"privateKey": "private-key", "username": "alice"}
        )
        self.assertIn("HttpOnly", login.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", login.headers["Set-Cookie"])
        self.assertNotIn("Secure", login.headers["Set-Cookie"])
        self.assertEqual(
            self.client.get("/api/users/alice/key").json,
            {"publicKey": "public-key"},
        )

        albums = self.client.get("/api/albums")
        self.assertEqual(albums.status_code, 200)
        self.assertEqual(albums.json["albums"][0]["name"], "גלריה")

        created_album = self.post_json(
            "/api/albums", {"name": "Summer", "albumKey": "summer-key"}
        )
        self.assertEqual(created_album.status_code, 201)
        self.assertEqual(created_album.json, {"number": 2})
        album_directory = self.storage_root / "alice" / "002"
        self.assertTrue(album_directory.is_dir())

        uploaded = self.client.post(
            "/api/albums/2/photos",
            data={
                "metadata": '{"name":"photo"}',
                "albumVersion": "summer-key",
                "ciphertext": (io.BytesIO(b"e" * 17), "encrypted.bin"),
            },
            headers={"Origin": self.settings.origin},
            content_type="multipart/form-data",
        )
        self.assertEqual(uploaded.status_code, 201)
        photo_id = uploaded.json["id"]
        encrypted_file = album_directory / f"{photo_id}.bin"
        self.assertEqual(encrypted_file.read_bytes(), b"e" * 17)

        listing = self.client.get("/api/albums/alice/2/photos")
        self.assertEqual(
            listing.json["photos"],
            [{"id": photo_id, "metadata": '{"name":"photo"}'}],
        )
        downloaded = self.client.get(f"/api/photos/{photo_id}")
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.data, b"e" * 17)
        downloaded.close()

        deleted = self.post_json("/api/albums/2/delete", {})
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(encrypted_file.exists())
        self.assertEqual(self.client.get("/api/albums/alice/2/photos").status_code, 404)

        logout = self.post_json("/api/logout", {})
        self.assertEqual(logout.status_code, 200)
        self.assertIn("Max-Age=0", logout.headers["Set-Cookie"])
        self.assertEqual(self.client.get("/api/albums").status_code, 401)

    def test_username_reservations_and_shared_album_access(self):
        expected_reserved = {"con", "prn", "aux", "nul"}
        expected_reserved.update(f"com{number}" for number in range(1, 10))
        expected_reserved.update(f"lpt{number}" for number in range(1, 10))
        self.assertEqual(WINDOWS_RESERVED_DEVICE_NAMES, expected_reserved)

        database = self.application.extensions["gallery_database"]
        with database.connection() as connection:
            user = connection.execute(
                "SELECT email FROM users WHERE username='alice'"
            ).fetchone()
            self.assertIsNone(user)

        self.register_and_login()
        with database.connection() as connection:
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                ("bob", "bob@example.com", "record", "public", "private"),
            )
            connection.execute("INSERT INTO albums VALUES (?, 1, ?)", ("bob", "גלריה"))
            connection.execute(
                "INSERT INTO access VALUES (?, 1, ?, ?)", ("bob", "bob", "key")
            )

        denied_share = self.post_json(
            "/api/albums/1/share", {"username": "alice", "albumKey": "wrapped"}
        )
        self.assertEqual(denied_share.status_code, 400)
        self.assertEqual(
            self.post_json(
                "/api/albums/1/share",
                {"username": "bob", "albumKey": "wrapped"},
            ).status_code,
            200,
        )
        with patch(
            "gallery.routes.authentication.run_opaque_operation",
            side_effect=[{"serverLoginState": "bob-login-state"}, {}],
        ):
            login = self.post_json(
                "/api/auth/login/start",
                {"username": "bob", "startLoginRequest": "bob-login-request"},
            )
            self.assertEqual(login.status_code, 200)
            completed_login = self.post_json(
                "/api/auth/login/finish",
                {
                    "challenge": login.json["challenge"],
                    "finishLoginRequest": "bob-finish-request",
                    "device": "bob-device",
                },
            )
            self.assertEqual(completed_login.status_code, 200)
        album_rows = self.client.get("/api/albums")
        self.assertEqual(len(album_rows.json["albums"]), 2)

    def test_existing_database_and_encrypted_photo_file_are_reused(self):
        root = self.storage_root
        root.mkdir(parents=True, exist_ok=True)
        database = Database(root)
        database.initialize()
        photo_path = root / "legacy-user" / "001" / "existing-photo.bin"
        photo_path.parent.mkdir(parents=True)
        photo_path.write_bytes(b"existing-encrypted-content")
        with database.connection(write=True) as connection:
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                ("legacy-user", "legacy@example.com", "record", "public", "private"),
            )
            connection.execute(
                "INSERT INTO albums VALUES (?, 1, ?)", ("legacy-user", "גלריה")
            )
            connection.execute(
                "INSERT INTO access VALUES (?, 1, ?, ?)",
                ("legacy-user", "legacy-user", "key"),
            )
            connection.execute(
                "INSERT INTO photos VALUES (?, ?, ?, ?, ?)",
                ("existing-photo", "legacy-user", 1, "metadata", 123),
            )

        create_app(self.settings)
        with database.connection() as connection:
            saved_user = connection.execute(
                "SELECT username FROM users WHERE username='legacy-user'"
            ).fetchone()
            saved_photo = connection.execute(
                "SELECT id, uploaded FROM photos WHERE id='existing-photo'"
            ).fetchone()
        self.assertEqual(saved_user["username"], "legacy-user")
        self.assertEqual(tuple(saved_photo), ("existing-photo", 123))
        self.assertEqual(photo_path.read_bytes(), b"existing-encrypted-content")

    def test_windows_default_storage_stays_next_to_server_entry_point(self):
        with patch("gallery.services.storage.sys.platform", "win32"):
            self.assertEqual(
                default_storage_root(), SERVER_DIRECTORY / "server-storage"
            )

    def test_entry_point_and_waitress_runtime_start_and_close(self):
        with (
            patch("main.Settings.from_environment", return_value=self.settings),
            patch("main.create_app", return_value=self.application) as build_application,
            patch("main.serve") as start_server,
        ):
            main.main()
        build_application.assert_called_once_with(self.settings)
        start_server.assert_called_once_with(self.application, self.settings)

        listener = unittest.mock.Mock()
        with (
            patch("gallery.server_runtime.create_server", return_value=listener) as make_server,
            patch("gallery.server_runtime.tailscale_connection", return_value=nullcontext()),
        ):
            serve(self.application, self.settings)
        make_server.assert_called_once_with(
            self.application,
            host="127.0.0.1",
            port=8000,
            max_request_body_size=26 * 1024 * 1024,
            clear_untrusted_proxy_headers=True,
        )
        listener.run.assert_called_once_with()
        listener.close.assert_called_once_with()

    def test_tailscale_integration_is_lazy_and_disconnects_on_failure(self):
        settings = replace(
            self.settings,
            local_http=False,
            origin="https://home-gallery.example.ts.net",
            tailscale_enabled=True,
        )
        fake_tailscale = SimpleNamespace(
            connect=lambda: {
                "state": "Running",
                "dns_name": "home-gallery.example.ts.net.",
            },
            proxy=SimpleNamespace(
                start=lambda: {
                    "proxy_state": "running",
                    "listen_port": 443,
                    "proxy_https": True,
                }
            ),
            disconnect=unittest.mock.Mock(),
        )
        roleforge_module = ModuleType("roleforge")
        roleforge_module.load = unittest.mock.Mock(
            return_value=SimpleNamespace(tailscale=fake_tailscale)
        )
        with patch.dict(sys.modules, {"roleforge": roleforge_module}):
            with tailscale_connection(settings):
                pass
        fake_tailscale.disconnect.assert_called_once_with()

        fake_tailscale.connect = lambda: {
            "state": "Stopped",
            "dns_name": "wrong.example.ts.net",
        }
        with patch.dict(sys.modules, {"roleforge": roleforge_module}):
            with self.assertRaisesRegex(RuntimeError, "DNS name does not match"):
                with tailscale_connection(settings):
                    pass
        self.assertEqual(fake_tailscale.disconnect.call_count, 2)

    def test_main_import_and_installed_python_layout_have_no_import_side_effects(self):
        modules = installer_server_files()
        self.assertIn(SERVER_DIRECTORY / "main.py", modules)
        with tempfile.TemporaryDirectory() as temporary:
            installed_server = Path(temporary) / "release" / "server"
            installed_server.mkdir(parents=True)
            for module in modules:
                destination = installed_server / module.relative_to(SERVER_DIRECTORY)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(module, destination)
            installed_browser = Path(temporary) / "release" / "clients" / "browser"
            installed_browser.mkdir(parents=True)

            environment = os.environ.copy()
            environment.pop("GALLERY_ORIGIN", None)
            environment["OPAQUE_SERVER_SETUP"] = "temporary-test-setup"
            environment["GALLERY_LOCAL_HTTP"] = "1"
            environment.pop("GALLERY_TAILSCALE_ROLE", None)
            import_environment = environment.copy()
            import_environment.pop("OPAQUE_SERVER_SETUP", None)
            import_environment.pop("GALLERY_LOCAL_HTTP", None)
            import_check = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import main, sys; from pathlib import Path; "
                        "server = Path(main.__file__).resolve().parent; "
                        "assert not (server / 'server-storage').exists(); "
                        "assert 'roleforge' not in sys.modules"
                    ),
                ],
                cwd=installed_server,
                env=import_environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(import_check.returncode, 0, import_check.stderr)
            self.assertFalse((installed_server / "server-storage").exists())

            storage = Path(temporary) / "release" / "temporary-storage"
            app_check = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from pathlib import Path; import main; "
                        "from gallery.configuration import Settings; "
                        f"settings = Settings.from_environment(Path({str(storage)!r})); "
                        "application = main.create_app(settings); "
                        "assert application.test_client().get('/api/albums').status_code == 401"
                    ),
                ],
                cwd=installed_server,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(app_check.returncode, 0, app_check.stderr)
            self.assertTrue((storage / "gallery.sqlite3").is_file())

    def test_username_validation_allows_mixed_case(self):
        """Usernames with uppercase letters should be accepted."""
        valid_usernames = [
            "Alice",
            "ALICE",
            "AlIcE",
            "User_Name",
            "User123",
            "UsEr_123",
            "Aa1",  # minimum length 3
            "A" + "a" * 23,  # maximum length 24
        ]
        for username in valid_usernames:
            with self.subTest(username=username):
                self.assertEqual(validate_username(username), username)

    def test_username_validation_rejects_invalid_first_char(self):
        """Usernames must start with an ASCII letter."""
        invalid_usernames = [
            "1user",  # starts with digit
            "_user",  # starts with underscore
            "-user",  # starts with hyphen
            " user",  # starts with space
        ]
        for username in invalid_usernames:
            with self.subTest(username=username):
                with self.assertRaises(Exception):  # abort(400)
                    validate_username(username)

    def test_username_validation_rejects_windows_reserved_case_insensitive(self):
        """Windows reserved device names should be rejected case-insensitively."""
        for reserved in WINDOWS_RESERVED_DEVICE_NAMES:
            for variant in [reserved, reserved.upper(), reserved.capitalize(), reserved.title()]:
                with self.subTest(username=variant):
                    with self.assertRaises(Exception):  # abort(400)
                        validate_username(variant)

    def test_username_case_insensitive_duplicate_check(self):
        """Case-insensitive duplicate usernames should be detected."""
        database = self.application.extensions["gallery_database"]
        with database.connection(write=True) as connection:
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                ("Alice", "alice@example.com", "record", "public", "private"),
            )
        # Should detect case-insensitive duplicate
        self.assertTrue(is_username_taken_case_insensitive(database, "alice"))
        self.assertTrue(is_username_taken_case_insensitive(database, "ALICE"))
        self.assertTrue(is_username_taken_case_insensitive(database, "AlIcE"))
        # Different username should not be detected
        self.assertFalse(is_username_taken_case_insensitive(database, "bob"))

    def test_registration_rejects_case_insensitive_duplicate(self):
        """Registration should reject case-insensitive duplicate usernames."""
        database = self.application.extensions["gallery_database"]
        with database.connection(write=True) as connection:
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                ("Alice", "alice@example.com", "record", "public", "private"),
            )
        with patch(
            "gallery.routes.authentication.run_opaque_operation",
            return_value={},
        ):
            response = self.post_json(
                "/api/auth/register/start",
                {
                    "username": "alice",  # lowercase duplicate
                    "email": "different@example.com",
                    "registrationRequest": "registration-request",
                },
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["code"], "username_taken")
        self.assertEqual(response.json["error"], "שם המשתמש כבר תפוס. בחר שם אחר.")

    def test_registration_finish_returns_username_taken_for_uniqueness_conflict(self):
        """A username collision after registration starts uses the same API error."""
        with patch(
            "gallery.routes.authentication.run_opaque_operation",
            return_value={},
        ):
            registration = self.post_json(
                "/api/auth/register/start",
                {
                    "username": "raceuser",
                    "email": "raceuser@example.com",
                    "registrationRequest": "registration-request",
                },
            )
        self.assertEqual(registration.status_code, 200)

        database = self.application.extensions["gallery_database"]
        with database.connection(write=True) as connection:
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                ("RACEUSER", "other@example.com", "record", "public", "private"),
            )

        with patch(
            "gallery.routes.authentication.run_opaque_operation",
            return_value={},
        ):
            response = self.post_json(
                "/api/auth/register/finish",
                {
                    "challenge": registration.json["challenge"],
                    "registrationRecord": "registration-record",
                    "publicKey": "public-key",
                    "privateKey": "private-key",
                    "albumKey": "first-album-key",
                },
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["code"], "username_taken")
        self.assertEqual(response.json["error"], "שם המשתמש כבר תפוס. בחר שם אחר.")

    def test_invalid_username_error_explains_actual_rules(self):
        response = self.post_json(
            "/api/auth/register/start",
            {
                "username": "1alice",
                "email": "alice@example.com",
                "registrationRequest": "registration-request",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("3–24", response.json["error"])
        self.assertIn("אות אנגלית", response.json["error"])
        self.assertIn("Windows", response.json["error"])

    def test_password_minimum_length_eight_characters(self):
        """Passwords of 8 characters should be accepted during registration."""
        with patch(
            "gallery.routes.authentication.run_opaque_operation",
            side_effect=[{}, {}, {"serverLoginState": "login-state", "loginResponse": "response"}, {}],
        ):
            # Register with 8-character password
            registration = self.post_json(
                "/api/auth/register/start",
                {
                    "username": "testuser",
                    "email": "testuser@example.com",
                    "registrationRequest": "registration-request",
                },
            )
            self.assertEqual(registration.status_code, 200)
            completed_registration = self.post_json(
                "/api/auth/register/finish",
                {
                    "challenge": registration.json["challenge"],
                    "registrationRecord": "registration-record",
                    "publicKey": "public-key",
                    "privateKey": "private-key",
                    "albumKey": "first-album-key",
                },
            )
            self.assertEqual(completed_registration.status_code, 201)

    def test_password_longer_than_eight_characters(self):
        """Passwords longer than 8 characters should continue to work."""
        with patch(
            "gallery.routes.authentication.run_opaque_operation",
            side_effect=[{}, {}, {"serverLoginState": "login-state", "loginResponse": "response"}, {}],
        ):
            # Register with 20-character password
            registration = self.post_json(
                "/api/auth/register/start",
                {
                    "username": "longpass",
                    "email": "longpass@example.com",
                    "registrationRequest": "registration-request",
                },
            )
            self.assertEqual(registration.status_code, 200)
            completed_registration = self.post_json(
                "/api/auth/register/finish",
                {
                    "challenge": registration.json["challenge"],
                    "registrationRecord": "registration-record",
                    "publicKey": "public-key",
                    "privateKey": "private-key",
                    "albumKey": "first-album-key",
                },
            )
            self.assertEqual(completed_registration.status_code, 201)


if __name__ == "__main__":
    unittest.main()
