"""
Post-deployment testing tools for the Strands DevOps Agent.

Implements the full 8-point test checklist:
1. Container Running Test
2. Health Check Test (60s timeout)
3. Port Binding Test (socket connection)
4. Inter-Service Connectivity Test
5. Volume Mount Test
6. Environment Variable Test
7. Log Output Test
8. Resource Baseline Test
"""

import json
import os
import socket
import subprocess
import time
from datetime import datetime, timezone, timedelta
from strands import tool

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.logger import get_logger, log_exception

tests_log = get_logger("tests")
agent_log = get_logger("agent")


def _run_cmd(cmd: list[str], timeout: int = 60) -> dict:
    """Execute a command and return result dict."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=True)
        return {"success": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e)}


def _get_compose_services(file_path: str) -> list[str]:
    """Get list of service names from a compose file."""
    result = _run_cmd(["docker", "compose", "-f", file_path, "ps", "--format", "json"])
    if not result["success"]:
        return []
    services = []
    for line in result["stdout"].strip().split("\n"):
        if line.strip():
            try:
                data = json.loads(line)
                services.append(data.get("Name", data.get("Service", "")))
            except json.JSONDecodeError:
                continue
    return services


@tool
def run_post_deploy_tests(file_path: str, expected_services: str = "") -> str:
    """Run the full 8-point post-deployment test suite against deployed services.

    This runs after every compose up to verify the deployment is healthy.

    Args:
        file_path: Path to the docker-compose.yml file that was deployed.
        expected_services: Optional comma-separated list of expected service names.
                          If empty, auto-detects from the compose file.

    Returns:
        Full test report with PASS/WARN/FAIL verdicts for each test.
    """
    ist = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")

    agent_log.info(
        f"Running post-deploy tests for {file_path}",
        extra={"component": "testing"},
    )

    # Get services
    services = _get_compose_services(file_path)
    if expected_services:
        expected = [s.strip() for s in expected_services.split(",")]
    else:
        expected = services

    results = []
    pass_count = 0
    warn_count = 0
    fail_count = 0

    report_lines = [
        f"[{timestamp}] [TEST] ━━ DEPLOYMENT TEST REPORT ━━━━━━━━━━━━",
        f"[{timestamp}] [TEST] Compose File : {file_path}",
        f"[{timestamp}] [TEST] Services     : {', '.join(expected) if expected else 'none detected'}",
        f"[{timestamp}] [TEST] ─────────────────────────────────────",
    ]

    # ── TEST 1: Container Running Test ──────────────────
    running_result = _run_cmd(["docker", "compose", "-f", file_path, "ps", "--status", "running", "--format", "{{.Name}}"])
    running_containers = running_result["stdout"].split("\n") if running_result["stdout"] else []
    running_containers = [c.strip() for c in running_containers if c.strip()]

    all_result = _run_cmd(["docker", "compose", "-f", file_path, "ps", "--format", "{{.Name}}"])
    all_containers = all_result["stdout"].split("\n") if all_result["stdout"] else []
    all_containers = [c.strip() for c in all_containers if c.strip()]

    not_running = [c for c in all_containers if c not in running_containers]

    if not not_running and running_containers:
        report_lines.append(f"[{timestamp}] [PASS] Container Running Test   : ALL {len(running_containers)} running")
        pass_count += 1
    elif not_running:
        report_lines.append(f"[{timestamp}] [FAIL] Container Running Test   : {', '.join(not_running)} not running")
        fail_count += 1
    else:
        report_lines.append(f"[{timestamp}] [FAIL] Container Running Test   : No containers found")
        fail_count += 1

    # ── TEST 2: Health Check Test ──────────────────────
    health_results = []
    for container in running_containers:
        # Wait up to 60s for health
        healthy = False
        for _ in range(12):  # 12 * 5s = 60s
            result = _run_cmd(["docker", "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}no healthcheck{{end}}", container])
            status = result["stdout"].strip()
            if status == "healthy":
                healthy = True
                health_results.append(f"{container}=healthy")
                break
            elif status == "no healthcheck":
                health_results.append(f"{container}=no healthcheck")
                break
            elif status == "unhealthy":
                health_results.append(f"{container}=unhealthy")
                break
            time.sleep(5)
        if not healthy and f"{container}=" not in " ".join(health_results):
            health_results.append(f"{container}=timeout")

    unhealthy = [h for h in health_results if "unhealthy" in h or "timeout" in h]
    no_hc = [h for h in health_results if "no healthcheck" in h]

    if unhealthy:
        report_lines.append(f"[{timestamp}] [FAIL] Health Check Test        : {', '.join(health_results)}")
        fail_count += 1
    elif no_hc:
        report_lines.append(f"[{timestamp}] [WARN] Health Check Test        : {', '.join(health_results)}")
        warn_count += 1
    else:
        report_lines.append(f"[{timestamp}] [PASS] Health Check Test        : {', '.join(health_results)}")
        pass_count += 1

    # ── TEST 3: Port Binding Test ─────────────────────
    port_results = []
    for container in running_containers:
        result = _run_cmd(["docker", "port", container])
        if result["success"] and result["stdout"]:
            for port_line in result["stdout"].split("\n"):
                if "->" in port_line:
                    host_part = port_line.split("->")[-1].strip()
                    if ":" in host_part:
                        host_port = host_part.split(":")[-1]
                        try:
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(3)
                            conn_result = sock.connect_ex(("127.0.0.1", int(host_port)))
                            sock.close()
                            if conn_result == 0:
                                port_results.append(f"{host_port}=open")
                            else:
                                port_results.append(f"{host_port}=closed")
                        except Exception:
                            port_results.append(f"{host_port}=error")

    port_failures = [p for p in port_results if "closed" in p or "error" in p]
    if port_results and not port_failures:
        report_lines.append(f"[{timestamp}] [PASS] Port Binding Test        : {', '.join(port_results)}")
        pass_count += 1
    elif port_failures:
        report_lines.append(f"[{timestamp}] [FAIL] Port Binding Test        : {', '.join(port_results)}")
        fail_count += 1
    else:
        report_lines.append(f"[{timestamp}] [WARN] Port Binding Test        : No port mappings found")
        warn_count += 1

    # ── TEST 4: Inter-Service Connectivity Test ───────
    if len(running_containers) > 1:
        connectivity_results = []
        first_container = running_containers[0]
        for other in running_containers[1:]:
            result = _run_cmd(["docker", "exec", first_container, "ping", "-c", "1", "-W", "2", other])
            if result["success"]:
                connectivity_results.append(f"{other}=reachable")
            else:
                # Try with service name (shorter name)
                short_name = other.split("-")[-1] if "-" in other else other
                result2 = _run_cmd(["docker", "exec", first_container, "ping", "-c", "1", "-W", "2", short_name])
                if result2["success"]:
                    connectivity_results.append(f"{short_name}=reachable")
                else:
                    connectivity_results.append(f"{other}=unreachable")

        unreachable = [c for c in connectivity_results if "unreachable" in c]
        if unreachable:
            report_lines.append(f"[{timestamp}] [WARN] Connectivity Test        : {', '.join(connectivity_results)}")
            warn_count += 1
        else:
            report_lines.append(f"[{timestamp}] [PASS] Connectivity Test        : {', '.join(connectivity_results)}")
            pass_count += 1
    else:
        report_lines.append(f"[{timestamp}] [PASS] Connectivity Test        : Single service — skipped")
        pass_count += 1

    # ── TEST 5: Volume Mount Test ─────────────────────
    volume_results = []
    for container in running_containers:
        result = _run_cmd(["docker", "inspect", "--format", "{{range .Mounts}}{{.Destination}} {{end}}", container])
        if result["success"] and result["stdout"].strip():
            mounts = result["stdout"].strip().split()
            for mount in mounts[:2]:  # Test first 2 mounts
                # Write test file
                test_file = f"{mount}/.devops_test_{int(time.time())}"
                write_result = _run_cmd(["docker", "exec", container, "sh", "-c", f"echo test > {test_file} && cat {test_file} && rm {test_file}"])
                if write_result["success"]:
                    volume_results.append(f"{mount}=writable")
                else:
                    volume_results.append(f"{mount}=not_writable")

    if volume_results:
        not_writable = [v for v in volume_results if "not_writable" in v]
        if not_writable:
            report_lines.append(f"[{timestamp}] [WARN] Volume Mount Test        : {', '.join(volume_results)}")
            warn_count += 1
        else:
            report_lines.append(f"[{timestamp}] [PASS] Volume Mount Test        : {', '.join(volume_results)}")
            pass_count += 1
    else:
        report_lines.append(f"[{timestamp}] [PASS] Volume Mount Test        : No volumes to test")
        pass_count += 1

    # ── TEST 6: Environment Variable Test ─────────────
    env_results = []
    for container in running_containers:
        result = _run_cmd(["docker", "exec", container, "env"])
        if result["success"]:
            env_count = len(result["stdout"].split("\n"))
            env_results.append(f"{container}={env_count} vars")
        else:
            env_results.append(f"{container}=cannot read env")

    env_failures = [e for e in env_results if "cannot" in e]
    if env_failures:
        report_lines.append(f"[{timestamp}] [WARN] Environment Variable Test : {', '.join(env_results)}")
        warn_count += 1
    else:
        report_lines.append(f"[{timestamp}] [PASS] Environment Variable Test : {', '.join(env_results)}")
        pass_count += 1

    # ── TEST 7: Log Output Test ───────────────────────
    error_keywords = ["panic", "fatal", "error", "exception", "refused", "timeout"]
    log_issues = []
    for container in running_containers:
        result = _run_cmd(["docker", "logs", "--tail", "20", container])
        output = (result["stdout"] + " " + result["stderr"]).lower()
        found = [kw for kw in error_keywords if kw in output]
        if found:
            log_issues.append(f"{container}: found [{', '.join(found)}]")

    if log_issues:
        report_lines.append(f"[{timestamp}] [WARN] Log Output Test          : {'; '.join(log_issues)}")
        warn_count += 1
    else:
        report_lines.append(f"[{timestamp}] [PASS] Log Output Test          : No error keywords in startup logs")
        pass_count += 1

    # ── TEST 8: Resource Baseline Test ────────────────
    resource_warnings = []
    for container in running_containers:
        result = _run_cmd(["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}\t{{.MemPerc}}", container])
        if result["success"] and result["stdout"]:
            parts = result["stdout"].split("\t")
            if len(parts) >= 2:
                try:
                    cpu = float(parts[0].replace("%", ""))
                    mem = float(parts[1].replace("%", ""))
                    if cpu > 50:
                        resource_warnings.append(f"{container}: CPU={cpu}%")
                    if mem > 70:
                        resource_warnings.append(f"{container}: MEM={mem}%")
                except ValueError:
                    pass

    if resource_warnings:
        report_lines.append(f"[{timestamp}] [WARN] Resource Baseline Test   : {', '.join(resource_warnings)}")
        warn_count += 1
    else:
        report_lines.append(f"[{timestamp}] [PASS] Resource Baseline Test   : All containers within normal limits")
        pass_count += 1

    # ── Final verdict ─────────────────────────────────
    report_lines.append(f"[{timestamp}] [TEST] ─────────────────────────────────────")
    report_lines.append(f"[{timestamp}] [TEST] Result: {pass_count} PASS / {warn_count} WARN / {fail_count} FAIL")

    if fail_count > 0:
        verdict = "FAILED — rollback recommended"
    elif warn_count > 0:
        verdict = "ACCEPTED WITH WARNINGS"
    else:
        verdict = "SUCCESSFUL"
    report_lines.append(f"[{timestamp}] [TEST] Deployment: {verdict}")
    report_lines.append(f"[{timestamp}] [TEST] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Write to tests.log
    full_report = "\n".join(report_lines)
    tests_log.info(f"\n{full_report}", extra={"component": "testing"})

    return full_report
