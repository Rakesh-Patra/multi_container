"""
Temporal Worker — runs the workflow and activity execution engine.

This is the process that polls the Temporal server for tasks
and executes workflows/activities. Run this alongside the agent.

Usage:
    python temporal/worker.py

Prerequisites:
    - Temporal server running: temporal server start-dev
    - Server default: localhost:7233
"""

import asyncio
import os
import sys

# Force UTF-8 output on Windows consoles to prevent UnicodeEncodeError on emojis
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from temporalio.client import Client
from temporalio.worker import Worker

from temporal.activities import ALL_ACTIVITIES
from temporal.workflows import ALL_WORKFLOWS
from utils.logger import get_logger

agent_log = get_logger("agent")

# Configuration
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "docker-devops-queue")


async def run_worker():
    """Connect to Temporal and start the worker."""
    print(f"\n  Connecting to Temporal server at {TEMPORAL_HOST}...")
    agent_log.info(
        f"[TEMPORAL] Worker connecting to {TEMPORAL_HOST}",
        extra={"component": "temporal.worker"},
    )

    try:
        client = await Client.connect(TEMPORAL_HOST)
        print(f"  Connected to Temporal server")
    except Exception as e:
        print(f"\n  ERROR: Could not connect to Temporal at {TEMPORAL_HOST}")
        print(f"  {e}")
        print(f"\n  Make sure Temporal is running:")
        print(f"    temporal server start-dev")
        print(f"\n  Or set TEMPORAL_HOST env variable to your server address.")
        return

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=ALL_WORKFLOWS,
        activities=ALL_ACTIVITIES,
    )

    workflow_names = [w.__name__ for w in ALL_WORKFLOWS]
    activity_names = [a.__name__ for a in ALL_ACTIVITIES]

    print(f"\n  ━━ Temporal Worker Started ━━━━━━━━━━━━━━━━━")
    print(f"  Task Queue  : {TASK_QUEUE}")
    print(f"  Workflows   : {len(ALL_WORKFLOWS)} ({', '.join(workflow_names)})")
    print(f"  Activities  : {len(ALL_ACTIVITIES)}")
    print(f"  Web UI      : http://localhost:8233")
    print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"\n  Polling for tasks... (Ctrl+C to stop)\n")

    agent_log.info(
        f"[TEMPORAL] Worker started: queue={TASK_QUEUE}, "
        f"workflows={len(ALL_WORKFLOWS)}, activities={len(ALL_ACTIVITIES)}",
        extra={"component": "temporal.worker"},
    )

    try:
        await worker.run()
    except KeyboardInterrupt:
        print("\n  Worker stopped.")
    except Exception as e:
        print(f"\n  Worker error: {e}")
        agent_log.error(
            f"[TEMPORAL] Worker error: {e}",
            extra={"component": "temporal.worker"},
        )


if __name__ == "__main__":
    print("\n  🐳 Docker DevOps Agent — Temporal Worker")
    print("  ─────────────────────────────────────────")
    asyncio.run(run_worker())
