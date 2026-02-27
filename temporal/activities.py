"""
Temporal Activities — wraps existing DevOps tools as durable activities.

Each activity calls an existing tool function but adds:
- Automatic retry on transient failures
- Timeout enforcement
- Full execution history in Temporal
- Heartbeat for long-running operations
"""

import os
import sys
from dataclasses import dataclass
from temporalio import activity

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.logger import get_logger

agent_log = get_logger("agent")


# ── Data classes for activity inputs/outputs ──────────
@dataclass
class ComposeInput:
    file_path: str
    build: bool = False
    detach: bool = True


@dataclass
class TestInput:
    file_path: str
    expected_services: str = ""


@dataclass
class BackupInput:
    file_path: str


@dataclass
class HealthCheckResult:
    report: str
    has_failures: bool = False


@dataclass
class DeployResult:
    success: bool
    message: str
    test_report: str = ""


@dataclass
class RollbackInput:
    current_file: str
    backup_file: str = ""


# ── Activities ────────────────────────────────────────
@activity.defn(name="validate_compose")
async def validate_compose_activity(file_path: str) -> str:
    """Validate a compose file — wraps compose_validate tool."""
    activity.logger.info(f"Validating: {file_path}")
    agent_log.info(f"[TEMPORAL] Validating compose: {file_path}", extra={"component": "temporal.activity"})

    from tools.compose_tools import compose_validate
    result = compose_validate(file_path=file_path)
    return result


@activity.defn(name="backup_compose")
async def backup_compose_activity(input: BackupInput) -> str:
    """Backup a compose file — wraps backup_compose_file tool."""
    activity.logger.info(f"Backing up: {input.file_path}")
    agent_log.info(f"[TEMPORAL] Backup: {input.file_path}", extra={"component": "temporal.activity"})

    from tools.compose_tools import backup_compose_file
    result = backup_compose_file(file_path=input.file_path)
    return result


@activity.defn(name="detect_conflicts")
async def detect_conflicts_activity(file_path: str) -> str:
    """Detect port conflicts — wraps detect_port_conflicts tool."""
    activity.logger.info(f"Checking ports: {file_path}")

    from tools.monitoring_tools import detect_port_conflicts
    result = detect_port_conflicts(file_path=file_path)
    return result


@activity.defn(name="deploy_compose")
async def deploy_compose_activity(input: ComposeInput) -> str:
    """Deploy services — wraps compose_up tool."""
    activity.logger.info(f"Deploying: {input.file_path}")
    agent_log.info(f"[TEMPORAL] Deploy: {input.file_path}", extra={"component": "temporal.activity"})

    # Heartbeat for long-running deploys
    activity.heartbeat("Starting deployment...")

    from tools.compose_tools import compose_up
    result = compose_up(file_path=input.file_path, build=input.build, detach=input.detach)

    activity.heartbeat("Deployment command completed")
    return result


@activity.defn(name="teardown_compose")
async def teardown_compose_activity(input: ComposeInput) -> str:
    """Tear down services — wraps compose_down tool."""
    activity.logger.info(f"Tearing down: {input.file_path}")
    agent_log.info(f"[TEMPORAL] Teardown: {input.file_path}", extra={"component": "temporal.activity"})

    from tools.compose_tools import compose_down
    result = compose_down(file_path=input.file_path, remove_volumes=False)
    return result


@activity.defn(name="run_tests")
async def run_tests_activity(input: TestInput) -> str:
    """Run post-deploy test suite — wraps run_post_deploy_tests tool."""
    activity.logger.info(f"Running tests: {input.file_path}")
    agent_log.info(f"[TEMPORAL] Tests: {input.file_path}", extra={"component": "temporal.activity"})

    activity.heartbeat("Running 8-point test suite...")

    from tools.testing_tools import run_post_deploy_tests
    result = run_post_deploy_tests(
        file_path=input.file_path,
        expected_services=input.expected_services,
    )
    return result


@activity.defn(name="health_check")
async def health_check_activity() -> HealthCheckResult:
    """Run health checks on all containers — wraps health_check_all tool."""
    activity.logger.info("Running health check")

    from tools.docker_tools import health_check_all
    report = health_check_all()

    has_failures = "unhealthy" in report.lower() or "error" in report.lower()
    return HealthCheckResult(report=report, has_failures=has_failures)


@activity.defn(name="get_stats")
async def get_stats_activity() -> str:
    """Get container stats — wraps get_container_stats tool."""
    from tools.docker_tools import get_container_stats
    return get_container_stats(container_name="")


@activity.defn(name="list_containers")
async def list_containers_activity() -> str:
    """List all containers — wraps list_containers tool."""
    from tools.docker_tools import list_containers
    return list_containers(all_containers=True)


@activity.defn(name="agent_analyze")
async def agent_analyze_activity(prompt: str) -> str:
    """Send a prompt to the Strands agent for AI-powered analysis.

    This activity creates the agent, runs the prompt, and returns the response.
    Useful for intelligent log analysis, root cause diagnosis, etc.
    """
    activity.logger.info(f"Agent analysis: {prompt[:80]}...")
    agent_log.info(f"[TEMPORAL] Agent analyze: {prompt[:80]}", extra={"component": "temporal.activity"})

    activity.heartbeat("Agent is thinking...")

    from container_agent import create_agent
    agent = create_agent()
    result = agent(prompt)

    return str(result)


@activity.defn(name="send_notification")
async def send_notification_activity(message: str) -> str:
    """Log a notification message (extensible to Slack/Discord/email later).

    Args:
        message: The notification message to send.
    """
    agent_log.info(f"[NOTIFICATION] {message}", extra={"component": "temporal.notify"})
    # Future: add Slack webhook, Discord, email, etc.
    return f"Notification sent: {message}"


# ── Registry of all activities ────────────────────────
ALL_ACTIVITIES = [
    validate_compose_activity,
    backup_compose_activity,
    detect_conflicts_activity,
    deploy_compose_activity,
    teardown_compose_activity,
    run_tests_activity,
    health_check_activity,
    get_stats_activity,
    list_containers_activity,
    agent_analyze_activity,
    send_notification_activity,
]
