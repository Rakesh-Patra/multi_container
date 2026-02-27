"""
Temporal Client — start and manage workflows from the CLI or agent.

Usage:
    python temporal/client.py deploy ./compose_files/docker-compose.yml
    python temporal/client.py monitor
    python temporal/client.py rollback ./compose_files/docker-compose.yml
    python temporal/client.py status <workflow-id>

Prerequisites:
    - Temporal server running: temporal server start-dev
    - Worker running: python temporal/worker.py
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

# Force UTF-8 output on Windows consoles to prevent UnicodeEncodeError on emojis
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from temporalio.client import Client

from temporal.activities import RollbackInput
from utils.logger import get_logger

agent_log = get_logger("agent")

# Configuration
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "docker-devops-queue")


async def get_client() -> Client:
    """Get a connected Temporal client."""
    return await Client.connect(TEMPORAL_HOST)


async def start_deploy(file_path: str) -> str:
    """Start a DeployWorkflow for the given compose file.

    Args:
        file_path: Path to the compose file to deploy.

    Returns:
        Workflow ID for tracking.
    """
    client = await get_client()

    ist = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime.now(ist).strftime("%Y%m%d-%H%M%S")
    workflow_id = f"deploy-{timestamp}-{uuid.uuid4().hex[:6]}"

    handle = await client.start_workflow(
        "DeployWorkflow",
        file_path,
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    agent_log.info(
        f"[TEMPORAL] Deploy workflow started: {workflow_id}",
        extra={"component": "temporal.client"},
    )

    print(f"\n  Deploy workflow started!")
    print(f"  Workflow ID : {workflow_id}")
    print(f"  File        : {file_path}")
    print(f"  Track at    : http://localhost:8233/namespaces/default/workflows/{workflow_id}")
    print(f"\n  Waiting for result...\n")

    # Wait for result
    result = await handle.result()
    return result


async def start_health_monitor(interval: int = 60) -> str:
    """Start a HealthMonitorWorkflow for continuous monitoring.

    Args:
        interval: Seconds between health checks. Defaults to 60.

    Returns:
        Workflow ID for tracking.
    """
    client = await get_client()

    ist = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime.now(ist).strftime("%Y%m%d-%H%M%S")
    workflow_id = f"health-monitor-{timestamp}"

    handle = await client.start_workflow(
        "HealthMonitorWorkflow",
        interval,
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    agent_log.info(
        f"[TEMPORAL] Health monitor started: {workflow_id}",
        extra={"component": "temporal.client"},
    )

    print(f"\n  Health monitor workflow started!")
    print(f"  Workflow ID : {workflow_id}")
    print(f"  Interval    : {interval}s")
    print(f"  Track at    : http://localhost:8233/namespaces/default/workflows/{workflow_id}")
    print(f"\n  Monitor is running in the background. Check Temporal Web UI for details.")

    return workflow_id


async def start_rollback(current_file: str, backup_file: str = "") -> str:
    """Start a RollbackWorkflow.

    Args:
        current_file: Path to the current (failing) compose file.
        backup_file: Optional specific backup to roll back to.

    Returns:
        Rollback result.
    """
    client = await get_client()

    ist = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime.now(ist).strftime("%Y%m%d-%H%M%S")
    workflow_id = f"rollback-{timestamp}-{uuid.uuid4().hex[:6]}"

    handle = await client.start_workflow(
        "RollbackWorkflow",
        RollbackInput(current_file=current_file, backup_file=backup_file),
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    print(f"\n  Rollback workflow started!")
    print(f"  Workflow ID : {workflow_id}")
    print(f"  Current     : {current_file}")
    print(f"  Backup      : {backup_file or 'latest'}")
    print(f"\n  Waiting for result...\n")

    result = await handle.result()
    return result


async def check_status(workflow_id: str) -> str:
    """Check the status of a running workflow.

    Args:
        workflow_id: The workflow ID to check.

    Returns:
        Workflow status description.
    """
    client = await get_client()
    handle = client.get_workflow_handle(workflow_id)

    try:
        desc = await handle.describe()
        status = desc.status.name if desc.status else "UNKNOWN"
        print(f"\n  Workflow: {workflow_id}")
        print(f"  Status  : {status}")
        print(f"  Type    : {desc.workflow_type}")
        print(f"  Started : {desc.start_time}")
        if desc.close_time:
            print(f"  Closed  : {desc.close_time}")
        return status
    except Exception as e:
        return f"Could not find workflow: {e}"


# ── CLI Entry Point ───────────────────────────────────
async def main():
    """CLI interface for starting Temporal workflows."""
    if len(sys.argv) < 2:
        print("\n  Usage:")
        print("    python temporal/client.py deploy <compose-file>")
        print("    python temporal/client.py monitor [interval-seconds]")
        print("    python temporal/client.py rollback <compose-file> [backup-file]")
        print("    python temporal/client.py status <workflow-id>")
        return

    command = sys.argv[1].lower()

    try:
        if command == "deploy":
            if len(sys.argv) < 3:
                print("  ERROR: Provide compose file path")
                return
            result = await start_deploy(sys.argv[2])
            print(f"\n  Result:\n{result}")

        elif command == "monitor":
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 60
            await start_health_monitor(interval)

        elif command == "rollback":
            if len(sys.argv) < 3:
                print("  ERROR: Provide current compose file path")
                return
            backup = sys.argv[3] if len(sys.argv) > 3 else ""
            result = await start_rollback(sys.argv[2], backup)
            print(f"\n  Result:\n{result}")

        elif command == "status":
            if len(sys.argv) < 3:
                print("  ERROR: Provide workflow ID")
                return
            await check_status(sys.argv[2])

        else:
            print(f"  Unknown command: {command}")

    except Exception as e:
        print(f"\n  ERROR: {e}")
        print(f"  Make sure Temporal server and worker are running.")


if __name__ == "__main__":
    print("\n  🐳 Docker DevOps Agent — Temporal Client")
    print("  ─────────────────────────────────────────")
    asyncio.run(main())
