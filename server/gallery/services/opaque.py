"""Run the browser-side OPAQUE server operations through a persistent Node.js daemon."""

import json
import os
import subprocess
import threading
import atexit
import logging
import time
from typing import Optional
from dataclasses import dataclass

from flask import abort

from gallery.configuration import Settings

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreaker:
    """Circuit breaker for OPAQUE daemon failures."""
    failure_threshold: int = 5
    timeout: float = 30.0
    failures: int = 0
    last_failure: float = 0
    open: bool = False

    def call(self, func, *args, **kwargs):
        if self.open and time.time() - self.last_failure > self.timeout:
            self.open = False  # half-open state
            logger.info("Circuit breaker entering half-open state")
        if self.open:
            raise RuntimeError("Circuit breaker open - OPAQUE daemon unavailable")
        try:
            result = func(*args, **kwargs)
            self.failures = 0
            return result
        except Exception as e:
            self.failures += 1
            self.last_failure = time.time()
            if self.failures >= self.failure_threshold:
                self.open = True
                logger.error(f"Circuit breaker opened after {self.failures} failures")
            raise


class OpaqueDaemon:
    """Persistent Node.js process for OPAQUE operations."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, dict] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._started = False
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=settings.opaque_circuit_breaker_threshold,
            timeout=settings.opaque_circuit_breaker_timeout,
        )
        self._health_check_interval = 60  # seconds
        self._last_health_check = 0
        self._healthy = True
        self._request_timeout = settings.opaque_timeout_seconds

    def _start(self) -> None:
        """Start the Node.js daemon process."""
        if self._started:
            return

        script_path = str(self.settings.browser_directory / "opaque-server.mjs")
        env = {**os.environ, "OPAQUE_SERVER_SETUP": self.settings.opaque_setup}

        self._process = subprocess.Popen(
            ["node", script_path, "--daemon"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            env=env,
            bufsize=1,  # line buffered
        )

        # Start reader thread
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

        # Wait for ready signal
        for _ in range(50):  # 5 second timeout
            if self._process.poll() is not None:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                raise RuntimeError(f"OPAQUE daemon failed to start: {stderr}")
            time.sleep(0.1)

        self._started = True
        self._healthy = True
        logger.info("OPAQUE daemon started")

    def _read_loop(self) -> None:
        """Read responses from the daemon stdout."""
        assert self._process and self._process.stdout
        for line in self._process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from OPAQUE daemon: {line}")
                continue

            req_id = response.get("id")
            if req_id is not None and req_id in self._pending:
                self._responses[req_id] = response
                self._pending[req_id].set()

    def _send_request(self, operation: str, **data) -> dict:
        """Send a request to the daemon and wait for response."""
        # Prepare request outside lock
        self._request_id += 1
        req_id = self._request_id
        request = {"id": req_id, "operation": operation, **data}
        event = threading.Event()

        with self._lock:
            if not self._started:
                self._start()

            if self._process is None or self._process.poll() is not None:
                # Process died, restart
                self._started = False
                self._start()

            assert self._process and self._process.stdin
            self._pending[req_id] = event

            try:
                self._process.stdin.write(json.dumps(request) + "\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self._pending.pop(req_id, None)
                logger.error(f"Failed to send to OPAQUE daemon: {e}")
                self._started = False
                raise RuntimeError("OPAQUE daemon communication failed")

        # Wait for response with timeout
        if not event.wait(timeout=self._request_timeout):
            with self._lock:
                self._pending.pop(req_id, None)
            raise TimeoutError("OPAQUE operation timed out")

        with self._lock:
            response = self._responses.pop(req_id, None)
            self._pending.pop(req_id, None)

        if response is None:
            raise RuntimeError("No response from OPAQUE daemon")

        if response.get("error"):
            abort(401, response["error"])

        return response.get("result", {})

    def health_check(self) -> bool:
        """Check if daemon process is alive and responsive."""
        now = time.time()
        if now - self._last_health_check < self._health_check_interval:
            return self._healthy

        self._last_health_check = now
        try:
            # Check if process is alive
            with self._lock:
                if self._process is None or self._process.poll() is not None:
                    self._healthy = False
                    return False
            # Process is alive, consider healthy
            self._healthy = True
        except Exception as e:
            logger.warning(f"OPAQUE health check failed: {e}")
            self._healthy = False
        return self._healthy

    def close(self) -> None:
        """Shutdown the daemon."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            self._process = None
        self._started = False
        self._healthy = False
        logger.info("OPAQUE daemon stopped")


# Global daemon instance
_daemon: Optional[OpaqueDaemon] = None
_daemon_lock = threading.Lock()


def get_daemon(settings: Settings) -> OpaqueDaemon:
    """Get or create the global OPAQUE daemon."""
    global _daemon
    with _daemon_lock:
        if _daemon is None:
            _daemon = OpaqueDaemon(settings)
            atexit.register(_daemon.close)
        return _daemon


def run_opaque_operation(settings: Settings, operation: str, **data):
    """Run an OPAQUE operation via the persistent daemon with circuit breaker."""
    daemon = get_daemon(settings)
    try:
        return daemon._circuit_breaker.call(daemon._send_request, operation, **data)
    except (RuntimeError, TimeoutError, BrokenPipeError) as e:
        logger.error(f"OPAQUE operation failed: {e}")
        abort(503, "רכיב האימות אינו זמין")