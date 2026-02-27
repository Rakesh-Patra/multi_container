"""
Structured logging module for the Docker DevOps Agent.

Log files:
- agent.log       : General agent activity
- compose.log     : Docker compose operations
- health.log      : Health check results
- monitor.log     : Monitoring and metrics
- exceptions.log  : Exceptions and errors
- tests.log       : Test results

Format: [TIMESTAMP] [LEVEL] [COMPONENT] message
Rotation: 10MB max, keep last 5 rotations
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Log directory ──────────────────────────────────────
LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Custom formatter ──────────────────────────────────
class DevOpsFormatter(logging.Formatter):
    """Custom formatter: [TIMESTAMP] [LEVEL] [COMPONENT] message"""

    def format(self, record):
        ist = timezone(timedelta(hours=5, minutes=30))
        timestamp = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname.ljust(8)
        component = getattr(record, "component", record.name)
        message = record.getMessage()
        return f"[{timestamp}] [{level}] [{component}] {message}"


# ── Logger factory ─────────────────────────────────────
_loggers = {}

LOG_FILES = {
    "agent": "agent.log",
    "compose": "compose.log",
    "health": "health.log",
    "monitor": "monitor.log",
    "exceptions": "exceptions.log",
    "tests": "tests.log",
}

MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5


def get_logger(name: str) -> logging.Logger:
    """
    Get or create a named logger that writes to the appropriate log file.

    Args:
        name: One of 'agent', 'compose', 'health', 'monitor', 'exceptions', 'tests'

    Returns:
        Configured logging.Logger instance
    """
    if name in _loggers:
        return _loggers[name]

    log_file = LOG_FILES.get(name, f"{name}.log")
    log_path = LOGS_DIR / log_file

    logger = logging.getLogger(f"devops.{name}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Rotating file handler
    handler = RotatingFileHandler(
        str(log_path),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(DevOpsFormatter())
    logger.addHandler(handler)

    # Also log to console for agent and exceptions
    if name in ("agent", "exceptions"):
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        console.setFormatter(DevOpsFormatter())
        logger.addHandler(console)

    _loggers[name] = logger
    return logger


def log_exception(
    component: str,
    exc_type: str,
    message: str,
    input_data: str,
    response: str,
    safe_state: bool,
):
    """
    Log a structured exception to exceptions.log in the required format.

    Args:
        component: The component/tool that raised the exception
        exc_type: The exception type (e.g. subprocess.CalledProcessError)
        message: The full exception message
        input_data: Sanitized input that caused it (no secrets)
        response: Action taken (retry / rollback / halt / alert)
        safe_state: Whether the system is still in a safe state
    """
    logger = get_logger("exceptions")
    ist = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
    safe = "YES" if safe_state else "NO"

    entry = (
        f"\n━━ EXCEPTION CAPTURED ━━━━━━━━━━━━━━━━━\n"
        f"Time      : {timestamp}\n"
        f"Component : {component}\n"
        f"Type      : {exc_type}\n"
        f"Message   : {message}\n"
        f"Input     : {input_data}\n"
        f"Response  : {response}\n"
        f"Safe State: {safe}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    logger.error(entry, extra={"component": component})
    return entry


def log_session_start():
    """Log agent session startup with timestamp."""
    logger = get_logger("agent")
    ist = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
    logger.info(
        f"━━ SESSION STARTED ━━ Timestamp: {timestamp}",
        extra={"component": "agent"},
    )
