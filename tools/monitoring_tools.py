"""
Monitoring and system management tools for the Strands DevOps Agent.

Tools:
- check_port            : Check if a port is available on the host
- detect_port_conflicts : Find ports in use that conflict with compose mappings
- prune_docker_system   : Prune unused Docker resources (with dry-run)
- get_disk_usage        : Docker disk usage report
"""

import json
import os
import socket
import subprocess
from strands import tool

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.logger import get_logger, log_exception

monitor_log = get_logger("monitor")
agent_log = get_logger("agent")


def _run_cmd(cmd: list[str], timeout: int = 60) -> dict:
    """Execute a command and return result dict."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=True)
        return {"success": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e)}


@tool
def check_port(port: int, host: str = "127.0.0.1") -> str:
    """Check if a specific port is available (not in use) on the host.

    Args:
        port: Port number to check.
        host: Host address to check. Defaults to "127.0.0.1".

    Returns:
        Port availability status.
    """
    monitor_log.info(
        f"Checking port {port} on {host}",
        extra={"component": "monitor.port_check"},
    )

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            monitor_log.warning(
                f"Port {port} is IN USE on {host}",
                extra={"component": "monitor.port_check"},
            )
            return f"⚠ Port {port} is IN USE on {host}. It is NOT available."
        else:
            monitor_log.info(
                f"Port {port} is AVAILABLE on {host}",
                extra={"component": "monitor.port_check"},
            )
            return f"✓ Port {port} is AVAILABLE on {host}."
    except Exception as e:
        return f"ERROR: Could not check port {port}: {e}"


@tool
def detect_port_conflicts(file_path: str) -> str:
    """Detect port conflicts between a compose file's port mappings and currently used host ports.

    Args:
        file_path: Path to the docker-compose.yml file to check.

    Returns:
        Report of conflicting and available ports.
    """
    monitor_log.info(
        f"Detecting port conflicts for {file_path}",
        extra={"component": "monitor.port_conflicts"},
    )

    if not os.path.exists(file_path):
        return f"ERROR: File not found: {file_path}"

    # Parse compose file for ports
    try:
        import yaml
        with open(file_path, "r") as f:
            compose = yaml.safe_load(f)
    except Exception as e:
        return f"ERROR: Could not parse compose file: {e}"

    ports_to_check = []
    services = compose.get("services", {})
    for svc_name, svc_def in services.items():
        for port_mapping in svc_def.get("ports", []):
            port_str = str(port_mapping)
            if ":" in port_str:
                host_port = port_str.split(":")[0]
                try:
                    ports_to_check.append((svc_name, int(host_port)))
                except ValueError:
                    continue

    if not ports_to_check:
        return "No port mappings found in compose file."

    conflicts = []
    available = []

    for svc_name, port in ports_to_check:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()

            if result == 0:
                conflicts.append(f"  ⚠ Port {port} (service: {svc_name}) — IN USE")
            else:
                available.append(f"  ✓ Port {port} (service: {svc_name}) — available")
        except Exception:
            available.append(f"  ? Port {port} (service: {svc_name}) — could not check")

    report = ["━━ PORT CONFLICT REPORT ━━━━━━━━━━━━━━━━"]
    if conflicts:
        report.append("CONFLICTS DETECTED:")
        report.extend(conflicts)
        report.append("")
    report.append("AVAILABLE PORTS:")
    report.extend(available)
    report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if conflicts:
        monitor_log.warning(
            f"Port conflicts found: {len(conflicts)}",
            extra={"component": "monitor.port_conflicts"},
        )
    else:
        monitor_log.info(
            "No port conflicts detected",
            extra={"component": "monitor.port_conflicts"},
        )

    return "\n".join(report)


@tool
def prune_docker_system(dry_run: bool = True, prune_volumes: bool = False) -> str:
    """Prune unused Docker resources (containers, images, networks, optionally volumes).

    SAFETY: Always runs in dry-run mode first. Set dry_run=False to actually prune.
    Never prunes volumes unless explicitly requested.

    Args:
        dry_run: If True, only show what would be removed without actually removing. Defaults to True.
        prune_volumes: If True, also prune unused volumes. DANGEROUS. Defaults to False.

    Returns:
        List of resources that would be (or were) removed.
    """
    monitor_log.info(
        f"Pruning Docker system (dry_run={dry_run}, volumes={prune_volumes})",
        extra={"component": "monitor.prune"},
    )

    if dry_run:
        # Show what would be removed
        report = ["━━ DOCKER PRUNE DRY RUN ━━━━━━━━━━━━━━━"]

        # Stopped containers
        result = _run_cmd(["docker", "ps", "-a", "--filter", "status=exited", "--format", "{{.Names}} ({{.Image}})"])
        if result["stdout"]:
            report.append(f"\nStopped containers to remove:\n{result['stdout']}")
        else:
            report.append("\nNo stopped containers to remove.")

        # Dangling images
        result = _run_cmd(["docker", "images", "-f", "dangling=true", "--format", "{{.Repository}}:{{.Tag}} ({{.Size}})"])
        if result["stdout"]:
            report.append(f"\nDangling images to remove:\n{result['stdout']}")
        else:
            report.append("\nNo dangling images to remove.")

        # Unused networks
        result = _run_cmd(["docker", "network", "ls", "--filter", "type=custom", "--format", "{{.Name}}"])
        if result["stdout"]:
            report.append(f"\nCustom networks (may be pruned if unused):\n{result['stdout']}")

        if prune_volumes:
            result = _run_cmd(["docker", "volume", "ls", "-f", "dangling=true", "--format", "{{.Name}}"])
            if result["stdout"]:
                report.append(f"\n⚠ Dangling volumes to remove:\n{result['stdout']}")

        report.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        report.append("\nTo actually prune, call again with dry_run=False")
        return "\n".join(report)

    else:
        # Actually prune
        cmd = ["docker", "system", "prune", "-f"]
        if prune_volumes:
            cmd.append("--volumes")

        result = _run_cmd(cmd)

        if result["success"]:
            monitor_log.info(
                f"System pruned successfully",
                extra={"component": "monitor.prune"},
            )
            return f"✓ Docker system pruned.\n{result['stdout']}"
        else:
            return f"ERROR: Prune failed.\n{result['stderr']}"


@tool
def get_disk_usage() -> str:
    """Get Docker disk usage report showing images, containers, volumes, and build cache.

    Returns:
        Docker disk usage summary.
    """
    monitor_log.info(
        "Getting Docker disk usage",
        extra={"component": "monitor.disk_usage"},
    )

    result = _run_cmd(["docker", "system", "df"])

    if result["success"]:
        monitor_log.info(
            f"Disk usage:\n{result['stdout']}",
            extra={"component": "monitor.disk_usage"},
        )
        return f"━━ DOCKER DISK USAGE ━━━━━━━━━━━━━━━━━━\n{result['stdout']}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    else:
        return f"ERROR: Could not get disk usage.\n{result['stderr']}"
