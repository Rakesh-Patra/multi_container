"""
Configuration module for the Docker DevOps Agent.
Loads environment variables and defines paths.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# ── Paths ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
LOGS_DIR = BASE_DIR / "logs"
COMPOSE_DIR = BASE_DIR / "compose_files"
BACKUPS_DIR = BASE_DIR / "backups"

# Create directories if they don't exist
for d in [LOGS_DIR, COMPOSE_DIR, BACKUPS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Model Configuration ───────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-2.5-flash")

# ── Docker Configuration ──────────────────────────────
DOCKER_COMPOSE_CMD = "docker compose"  # Modern compose v2
HEALTHCHECK_TIMEOUT = 60  # seconds to wait for healthchecks
MAX_LOG_LINES = 100  # default tail lines for logs

# ── Temporal Configuration ────────────────────────────
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "docker-devops-queue")

