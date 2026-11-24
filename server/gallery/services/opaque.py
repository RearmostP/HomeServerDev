"""Run the browser-side OPAQUE server operations through the local Node helper."""

import json
import os
import subprocess

from flask import abort

from gallery.configuration import Settings


def run_opaque_operation(settings: Settings, operation: str, **data):
    result = subprocess.run(
        ["node", str(settings.browser_directory / "opaque-server.mjs")],
        input=json.dumps({"operation": operation, **data}),
        capture_output=True,
        encoding="utf-8",
        timeout=15,
        env={**os.environ, "OPAQUE_SERVER_SETUP": settings.opaque_setup},
    )
    if result.returncode:
        abort(503, "רכיב האימות אינו זמין")
    response = json.loads(result.stdout)
    if response is None:
        abort(401, "פרטי אימות שגויים")
    return response
