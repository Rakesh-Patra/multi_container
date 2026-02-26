"""
Docker container management tools for the Strands DevOps Agent.

Tools:
- list_containers     : List all Docker containers
- get_container_logs  : Fetch container logs
- get_container_stats : CPU/memory stats snapshot
- health_check_all    : Health status of all running containers
- inspect_container   : Detailed container inspection
"""

import json
import subprocess
from strands import tool

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.logger import get_logger, log_exception

agent_log = get_logger("agent")
health_log = get_logger("health")


def _run_docker(cmd: list[str], component: str = "docker") -> dict:
    """
    Execute a docker command and return structured result.

    Returns:
        dict with keys: success (bool), stdout (str), stderr (str), returncode (int)
    """
    full_cmd = " ".join(cmd)
    logger = get_logger("agent")
    logger.info(f"Executing: {full_cmd}", extra={"component": component})

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            shell=True,
        )
        logger.info(
            f"Command completed: returncode={result.returncode}",
            extra={"component": component},
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        log_exception(
            component=component,
            exc_type="subprocess.TimeoutExpired",
            message=f"Command timed out after 120s: {full_cmd}",
            input_data=full_cmd,
            response="Command aborted due to timeout",
            safe_state=True,
        )
        return {
            "success": False,
            "stdout": "",
            "stderr": "Command timed out after 120 seconds",
            "returncode": -1,
        }
    except FileNotFoundError:
        log_exception(
            component=component,
            exc_type="FileNotFoundError",
            message="Docker command not found. Is Docker installed and in PATH?",
            input_data=full_cmd,
            response="Halted — Docker daemon not available",
            safe_state=True,
        )
        return {
            "success": False,
            "stdout": "",
            "stderr": "Docker not found. Please ensure Docker is installed and running.",
            "returncode": -1,
        }
    except Exception as e:
        log_exception(
            component=component,
            exc_type=type(e).__name__,
            message=str(e),
            input_data=full_cmd,
            response="Unexpected error — halted",
            safe_state=True,
        )
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Unexpected error: {str(e)}",
            "returncode": -1,
        }


@tool
def list_containers(all_containers: bool = True) -> str:
    """List all Docker containers with their status, names, images, and ports.

    Args:
        all_containers: If True, show all containers including stopped ones. Defaults to True.

    Returns:
        Formatted table of containers or error message.
    """
    agent_log.info(
        f"Listing containers (all={all_containers})",
        extra={"component": "docker.list_containers"},
    )

    cmd = ["docker", "ps", "--format", "table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]
    if all_containers:
        cmd.insert(2, "-a")

    result = _run_docker(cmd, "docker.list_containers")

    if result["success"]:
        agent_log.info(
            f"Listed containers successfully",
            extra={"component": "docker.list_containers"},
        )
        return result["stdout"] if result["stdout"] else "No containers found."
    else:
        return f"ERROR: Failed to list containers.\n{result['stderr']}"


@tool
def get_container_logs(container_name: str, tail: int = 50) -> str:
    """Fetch the last N lines of logs from a specific Docker container.

    Args:
        container_name: Name or ID of the container.
        tail: Number of log lines to fetch from the end. Defaults to 50.

    Returns:
        Container log output or error message.
    """
    agent_log.info(
        f"Fetching logs for '{container_name}' (tail={tail})",
        extra={"component": "docker.get_logs"},
    )

    cmd = ["docker", "logs", "--tail", str(tail), container_name]
    result = _run_docker(cmd, "docker.get_logs")

    if result["success"]:
        # Docker logs go to both stdout and stderr
        output = result["stdout"] or result["stderr"]
        return output if output else f"No logs available for '{container_name}'."
    else:
        return f"ERROR: Failed to fetch logs for '{container_name}'.\n{result['stderr']}"


@tool
def get_container_stats(container_name: str = "") -> str:
    """Get CPU and memory usage stats for Docker containers (non-streaming snapshot).

    Args:
        container_name: Optional. Name/ID of a specific container. If empty, shows all running containers.

    Returns:
        Formatted stats table or error message.
    """
    agent_log.info(
        f"Getting stats for '{container_name or 'all containers'}'",
        extra={"component": "docker.get_stats"},
    )

    cmd = ["docker", "stats", "--no-stream", "--format",
           "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.PIDs}}"]
    if container_name:
        cmd.append(container_name)

    result = _run_docker(cmd, "docker.get_stats")

    if result["success"]:
        monitor_log = get_logger("monitor")
        monitor_log.info(
            f"Stats snapshot:\n{result['stdout']}",
            extra={"component": "docker.get_stats"},
        )
        return result["stdout"] if result["stdout"] else "No running containers to report stats on."
    else:
        return f"ERROR: Failed to get stats.\n{result['stderr']}"


@tool
def health_check_all() -> str:
    """Check the health status of all running Docker containers.

    Returns:
        Health status report for all running containers.
    """
    health_log.info(
        "Running health check on all containers",
        extra={"component": "docker.health_check"},
    )

    cmd = ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}"]
    result = _run_docker(cmd, "docker.health_check")

    if not result["success"]:
        return f"ERROR: Could not list containers for health check.\n{result['stderr']}"

    if not result["stdout"]:
        return "No running containers found."

    lines = result["stdout"].strip().split("\n")
    report = []
    report.append("━━ HEALTH CHECK REPORT ━━━━━━━━━━━━━━━━━")

    for line in lines:
        parts = line.split("\t")
        if len(parts) >= 3:
            cid, name, status = parts[0], parts[1], parts[2]

            # Get detailed health via inspect
            inspect_cmd = ["docker", "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}no healthcheck{{end}}", cid]
            inspect_result = _run_docker(inspect_cmd, "docker.health_check")
            health_status = inspect_result["stdout"] if inspect_result["success"] else "unknown"

            report.append(f"  {name}: status={status}, health={health_status}")

            health_log.info(
                f"{name}: status={status}, health={health_status}",
                extra={"component": "docker.health_check"},
            )

    report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(report)


@tool
def inspect_container(container_name: str) -> str:
    """Get detailed inspection data for a specific Docker container.

    Args:
        container_name: Name or ID of the container to inspect.

    Returns:
        JSON-formatted inspection data or error message.
    """
    agent_log.info(
        f"Inspecting container '{container_name}'",
        extra={"component": "docker.inspect"},
    )

    cmd = ["docker", "inspect", container_name]
    result = _run_docker(cmd, "docker.inspect")

    if result["success"]:
        try:
            data = json.loads(result["stdout"])
            if data:
                c = data[0]
                summary = {
                    "Name": c.get("Name", ""),
                    "Id": c.get("Id", "")[:12],
                    "State": c.get("State", {}).get("Status", ""),
                    "Health": c.get("State", {}).get("Health", {}).get("Status", "no healthcheck"),
                    "Image": c.get("Config", {}).get("Image", ""),
                    "Ports": c.get("NetworkSettings", {}).get("Ports", {}),
                    "Mounts": [m.get("Destination", "") for m in c.get("Mounts", [])],
                    "RestartCount": c.get("RestartCount", 0),
                    "ExitCode": c.get("State", {}).get("ExitCode", ""),
                    "StartedAt": c.get("State", {}).get("StartedAt", ""),
                    "Networks": list(c.get("NetworkSettings", {}).get("Networks", {}).keys()),
                }
                return json.dumps(summary, indent=2)
        except json.JSONDecodeError:
            pass
        return result["stdout"]
    else:
        return f"ERROR: Failed to inspect '{container_name}'.\n{result['stderr']}"
