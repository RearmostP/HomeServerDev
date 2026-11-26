"""Structured logging configuration for the gallery server."""

import json
import logging
import sys
import time
from typing import Any


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields if present
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "name", "pathname", "process", "processName",
                "relativeCreated", "thread", "threadName", "exc_info",
                "exc_text", "stack_info"
            }:
                log_data[key] = value

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(json_format: bool = False, level: int = logging.INFO) -> None:
    """Configure application logging."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]

    # Reduce noise from third-party loggers
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


class RequestLogger:
    """Middleware for logging HTTP requests."""

    def __init__(self, app, logger: logging.Logger | None = None):
        self.app = app
        self.logger = logger or logging.getLogger("gallery.requests")

    def __call__(self, environ, start_response):
        start_time = time.time()
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "")

        # Skip logging for health/metrics endpoints to reduce noise
        if path in ("/health", "/metrics"):
            return self.app(environ, start_response)

        def logging_start_response(status, headers, exc_info=None):
            duration_ms = (time.time() - start_time) * 1000
            status_code = int(status.split()[0])

            self.logger.info(
                "HTTP request",
                extra={
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                    "remote_addr": environ.get("REMOTE_ADDR"),
                    "user_agent": environ.get("HTTP_USER_AGENT"),
                }
            )
            return start_response(status, headers, exc_info)

        return self.app(environ, logging_start_response)