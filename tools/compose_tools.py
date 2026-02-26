"""
Docker Compose lifecycle tools for the Strands DevOps Agent.

Tools:
- compose_validate      : Validate a compose file
- compose_up            : Deploy services from a compose file
- compose_down          : Tear down services
- compose_generate      : Generate a compose YAML from service specs
- compose_diff          : Diff two compose files
- backup_compose_file   : Backup a compose file with timestamp
"""

import json
import os
import shutil
import subprocess
import yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path
from strands import tool

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.logger import get_logger, log_exception
from config import COMPOSE_DIR, BACKUPS_DIR

compose_log = get_logger("compose")
agent_log = get_logger("agent")


def _run_compose(cmd: list[str], component: str = "compose") -> dict:
    """Execute a docker compose command and return structured result."""
    full_cmd = " ".join(cmd)
    compose_log.info(f"Executing: {full_cmd}", extra={"component": component})

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, shell=True
        )
        compose_log.info(
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
            message=f"Compose command timed out after 300s: {full_cmd}",
            input_data=full_cmd,
            response="Command aborted due to timeout",
            safe_state=True,
        )
        return {"success": False, "stdout": "", "stderr": "Command timed out", "returncode": -1}
    except Exception as e:
        log_exception(
            component=component,
            exc_type=type(e).__name__,
            message=str(e),
            input_data=full_cmd,
            response="Unexpected error — halted",
            safe_state=True,
        )
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}


@tool
def compose_validate(file_path: str) -> str:
    """Validate a Docker Compose file for syntax and configuration errors.

    Args:
        file_path: Path to the docker-compose.yml file to validate.

    Returns:
        Validation result — either success confirmation or detailed error.
    """
    compose_log.info(
        f"Validating compose file: {file_path}",
        extra={"component": "compose.validate"},
    )

    if not os.path.exists(file_path):
        log_exception(
            component="compose.validate",
            exc_type="FileNotFoundError",
            message=f"Compose file not found: {file_path}",
            input_data=f"file_path={file_path}",
            response="Validation aborted — file does not exist",
            safe_state=True,
        )
        return f"ERROR: Compose file not found: {file_path}\nPlease check the path or generate a new compose file."

    cmd = ["docker", "compose", "-f", file_path, "config"]
    result = _run_compose(cmd, "compose.validate")

    if result["success"]:
        compose_log.info(
            f"Validation PASSED for {file_path}",
            extra={"component": "compose.validate"},
        )
        return f"✓ Compose file '{file_path}' is valid.\n\nResolved configuration:\n{result['stdout']}"
    else:
        log_exception(
            component="compose.validate",
            exc_type="ComposeValidationError",
            message=result["stderr"],
            input_data=f"file_path={file_path}",
            response="Validation failed — file not applied",
            safe_state=True,
        )
        return f"✗ Validation FAILED for '{file_path}':\n{result['stderr']}"


@tool
def compose_up(file_path: str, build: bool = False, detach: bool = True) -> str:
    """Deploy services from a Docker Compose file.

    Args:
        file_path: Path to the docker-compose.yml file.
        build: If True, build images before starting. Defaults to False.
        detach: If True, run in detached mode. Defaults to True.

    Returns:
        Deployment result with status of each service.
    """
    compose_log.info(
        f"Bringing up services from {file_path} (build={build}, detach={detach})",
        extra={"component": "compose.up"},
    )

    # Step 1: Validate first
    if not os.path.exists(file_path):
        return f"ERROR: Compose file not found: {file_path}"

    validate_cmd = ["docker", "compose", "-f", file_path, "config", "-q"]
    validate_result = _run_compose(validate_cmd, "compose.up.validate")
    if not validate_result["success"]:
        return f"✗ Compose file validation failed. Not deploying.\n{validate_result['stderr']}"

    # Step 2: Bring up
    cmd = ["docker", "compose", "-f", file_path, "up"]
    if build:
        cmd.append("--build")
    if detach:
        cmd.append("-d")

    result = _run_compose(cmd, "compose.up")

    if result["success"]:
        compose_log.info(
            f"Services UP from {file_path}",
            extra={"component": "compose.up"},
        )
        # Get status of services
        ps_cmd = ["docker", "compose", "-f", file_path, "ps"]
        ps_result = _run_compose(ps_cmd, "compose.up.status")
        status_output = ps_result["stdout"] if ps_result["success"] else "Could not fetch service status."

        return (
            f"✓ Services deployed successfully from '{file_path}'.\n\n"
            f"Service Status:\n{status_output}\n\n"
            f"Output:\n{result['stdout']}\n{result['stderr']}"
        )
    else:
        log_exception(
            component="compose.up",
            exc_type="ComposeUpError",
            message=result["stderr"],
            input_data=f"file_path={file_path}, build={build}",
            response="Deployment failed — services not started",
            safe_state=True,
        )
        return f"✗ Deployment FAILED for '{file_path}':\n{result['stderr']}"


@tool
def compose_down(file_path: str, remove_volumes: bool = False) -> str:
    """Tear down services from a Docker Compose file.

    SAFETY: Volumes are NOT removed by default. Set remove_volumes=True only with explicit user confirmation.

    Args:
        file_path: Path to the docker-compose.yml file.
        remove_volumes: If True, also remove named volumes. DANGEROUS — data loss is irreversible. Defaults to False.

    Returns:
        Teardown result.
    """
    compose_log.info(
        f"Tearing down services from {file_path} (remove_volumes={remove_volumes})",
        extra={"component": "compose.down"},
    )

    if not os.path.exists(file_path):
        return f"ERROR: Compose file not found: {file_path}"

    if remove_volumes:
        compose_log.warning(
            "⚠ remove_volumes=True — named volumes WILL be deleted!",
            extra={"component": "compose.down"},
        )

    cmd = ["docker", "compose", "-f", file_path, "down"]
    if remove_volumes:
        cmd.append("-v")

    result = _run_compose(cmd, "compose.down")

    if result["success"]:
        compose_log.info(
            f"Services DOWN from {file_path}",
            extra={"component": "compose.down"},
        )
        return f"✓ Services torn down successfully from '{file_path}'.\n{result['stdout']}\n{result['stderr']}"
    else:
        return f"✗ Teardown FAILED:\n{result['stderr']}"


# ── Service-aware defaults for production compose generation ──
# Maps image name patterns to proper healthchecks and default volumes
SERVICE_DEFAULTS = {
    "nginx": {
        "healthcheck": {
            "test": ["CMD", "curl", "-f", "http://localhost/"],
            "interval": "15s",
            "timeout": "5s",
            "retries": 3,
            "start_period": "10s",
        },
        "volumes": [
            {"name": "nginx_config", "mount": "/etc/nginx/conf.d", "comment": "nginx configuration"},
            {"name": "nginx_html", "mount": "/usr/share/nginx/html", "comment": "static files"},
        ],
    },
    "redis": {
        "healthcheck": {
            "test": ["CMD", "redis-cli", "ping"],
            "interval": "15s",
            "timeout": "5s",
            "retries": 3,
            "start_period": "10s",
        },
        "volumes": [
            {"name": "redis_data", "mount": "/data", "comment": "redis persistence"},
        ],
    },
    "postgres": {
        "healthcheck": {
            "test": ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres}"],
            "interval": "15s",
            "timeout": "5s",
            "retries": 5,
            "start_period": "30s",
        },
        "volumes": [
            {"name": "postgres_data", "mount": "/var/lib/postgresql/data", "comment": "database files"},
        ],
    },
    "mysql": {
        "healthcheck": {
            "test": ["CMD", "mysqladmin", "ping", "-h", "localhost"],
            "interval": "15s",
            "timeout": "5s",
            "retries": 5,
            "start_period": "30s",
        },
        "volumes": [
            {"name": "mysql_data", "mount": "/var/lib/mysql", "comment": "database files"},
        ],
    },
    "mariadb": {
        "healthcheck": {
            "test": ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"],
            "interval": "15s",
            "timeout": "5s",
            "retries": 5,
            "start_period": "30s",
        },
        "volumes": [
            {"name": "mariadb_data", "mount": "/var/lib/mysql", "comment": "database files"},
        ],
    },
    "mongo": {
        "healthcheck": {
            "test": ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"],
            "interval": "15s",
            "timeout": "5s",
            "retries": 5,
            "start_period": "30s",
        },
        "volumes": [
            {"name": "mongo_data", "mount": "/data/db", "comment": "database files"},
        ],
    },
    "elasticsearch": {
        "healthcheck": {
            "test": ["CMD-SHELL", "curl -f http://localhost:9200/_cluster/health || exit 1"],
            "interval": "30s",
            "timeout": "10s",
            "retries": 5,
            "start_period": "60s",
        },
        "volumes": [
            {"name": "es_data", "mount": "/usr/share/elasticsearch/data", "comment": "index data"},
        ],
    },
    "rabbitmq": {
        "healthcheck": {
            "test": ["CMD", "rabbitmq-diagnostics", "-q", "ping"],
            "interval": "30s",
            "timeout": "10s",
            "retries": 3,
            "start_period": "30s",
        },
        "volumes": [
            {"name": "rabbitmq_data", "mount": "/var/lib/rabbitmq", "comment": "queue data"},
        ],
    },
}

# Fallback healthcheck for unknown services
DEFAULT_HEALTHCHECK = {
    "test": ["CMD-SHELL", "exit 0"],
    "interval": "30s",
    "timeout": "10s",
    "retries": 3,
    "start_period": "10s",
}


def _detect_service_type(image: str) -> str | None:
    """Detect service type from image name for smart defaults."""
    image_lower = image.lower().split(":")[0].split("/")[-1]
    for svc_type in SERVICE_DEFAULTS:
        if svc_type in image_lower:
            return svc_type
    return None


# ── Service role classification for auto-dependency detection ──
# Role determines startup order: database/cache → backend → frontend/proxy
SERVICE_ROLES = {
    "postgres": "database",
    "mysql": "database",
    "mariadb": "database",
    "mongo": "database",
    "elasticsearch": "database",
    "redis": "cache",
    "rabbitmq": "queue",
    "nginx": "proxy",
}

# Backend image patterns (not in SERVICE_DEFAULTS but common app images)
BACKEND_PATTERNS = [
    "python", "node", "golang", "java", "ruby", "php",
    "flask", "django", "express", "fastapi", "spring",
    "api", "backend", "app", "server", "web",
]

STAGE_ORDER = {
    "database": 1,
    "cache": 1,
    "queue": 1,
    "backend": 2,
    "proxy": 3,
    "unknown": 2,
}


def _detect_service_role(image: str, svc_type: str | None) -> str:
    """Classify a service's role for dependency ordering."""
    if svc_type and svc_type in SERVICE_ROLES:
        return SERVICE_ROLES[svc_type]

    image_lower = image.lower().split(":")[0].split("/")[-1]
    for pattern in BACKEND_PATTERNS:
        if pattern in image_lower:
            return "backend"
    return "unknown"


def _auto_detect_dependencies(services_info: list[dict]) -> dict[str, list[str]]:
    """Auto-detect depends_on based on service roles.

    Logic:
    - Stage 1 (database, cache, queue): no dependencies
    - Stage 2 (backend, unknown): depends on all Stage 1 services
    - Stage 3 (proxy): depends on all Stage 2 services

    Returns:
        Dict mapping service name to list of dependency names.
    """
    by_stage: dict[int, list[str]] = {1: [], 2: [], 3: []}

    for svc in services_info:
        stage = STAGE_ORDER.get(svc["role"], 2)
        by_stage[stage].append(svc["name"])

    deps: dict[str, list[str]] = {}

    # Stage 2 services depend on Stage 1
    for name in by_stage[2]:
        if by_stage[1]:
            deps[name] = by_stage[1]

    # Stage 3 services depend on Stage 2 (or Stage 1 if no Stage 2)
    for name in by_stage[3]:
        if by_stage[2]:
            deps[name] = by_stage[2]
        elif by_stage[1]:
            deps[name] = by_stage[1]

    return deps


@tool
def compose_generate(
    services: str,
    output_filename: str = "docker-compose.yml",
) -> str:
    """Generate a Docker Compose YAML file from a JSON service specification.

    The generated file follows all production standards:
    - Smart healthchecks per service type (redis-cli ping, pg_isready, curl for nginx, etc.)
    - Automatic data persistence volumes for known services (redis, postgres, mysql, etc.)
    - restart: unless-stopped
    - Resource limits (memory + CPU)
    - Named networks and volumes
    - Structured JSON logging driver
    - Traceability labels

    Args:
        services: JSON string describing services. Example:
            [{"name": "web", "image": "nginx:latest", "ports": ["8080:80"]},
             {"name": "db", "image": "postgres:15", "ports": ["5432:5432"],
              "environment": {"POSTGRES_PASSWORD": "${DB_PASSWORD}"}}]
        output_filename: Name of the output file. Saved to ./compose_files/. Defaults to "docker-compose.yml".

    Returns:
        Path to the generated file and its contents, or error message.
    """
    compose_log.info(
        f"Generating compose file: {output_filename}",
        extra={"component": "compose.generate"},
    )

    try:
        svc_list = json.loads(services)
    except json.JSONDecodeError as e:
        log_exception(
            component="compose.generate",
            exc_type="json.JSONDecodeError",
            message=str(e),
            input_data=services[:200],
            response="Generation aborted — invalid JSON input",
            safe_state=True,
        )
        return f"ERROR: Invalid JSON in services specification: {e}"

    ist = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime.now(ist).strftime("%Y-%m-%dT%H:%M:%S")

    compose = {"services": {}, "networks": {"app_network": {"driver": "bridge"}}, "volumes": {}}

    # ── Pass 1: Detect service roles and auto-compute dependencies ──
    services_info = []
    for svc in svc_list:
        name = svc.get("name", "service")
        image = svc.get("image", "alpine:latest")
        svc_type = _detect_service_type(image)
        role = _detect_service_role(image, svc_type)
        services_info.append({"name": name, "image": image, "svc_type": svc_type, "role": role})

    auto_deps = _auto_detect_dependencies(services_info)
    if auto_deps:
        compose_log.info(
            f"Auto-detected dependencies: {auto_deps}",
            extra={"component": "compose.generate"},
        )

    # ── Pass 2: Build service definitions ──
    for i, svc in enumerate(svc_list):
        name = svc.get("name", "service")
        image = svc.get("image", "alpine:latest")
        ports = svc.get("ports", [])
        environment = svc.get("environment", {})
        volumes = svc.get("volumes", [])
        command = svc.get("command", None)
        depends_on = svc.get("depends_on", [])

        # Use detected info from pass 1
        info = services_info[i]
        svc_type = info["svc_type"]
        role = info["role"]
        stage = STAGE_ORDER.get(role, 2)
        defaults = SERVICE_DEFAULTS.get(svc_type, {}) if svc_type else {}

        # Use service-specific healthcheck or fallback
        healthcheck = defaults.get("healthcheck", DEFAULT_HEALTHCHECK)

        service_def = {
            "image": image,
            "restart": "unless-stopped",
            "healthcheck": healthcheck,
            "deploy": {
                "resources": {
                    "limits": {
                        "memory": svc.get("memory_limit", "512M"),
                        "cpus": svc.get("cpu_limit", "0.5"),
                    }
                }
            },
            "networks": ["app_network"],
            "logging": {
                "driver": "json-file",
                "options": {"max-size": "10m", "max-file": "3"},
            },
            "labels": {
                "managed-by": "docker-devops-agent",
                "created-at": timestamp,
                "environment": "development",
                "stage": f"{stage}-{role}",
            },
        }

        if ports:
            service_def["ports"] = ports
        if environment:
            service_def["environment"] = environment
        if command:
            service_def["command"] = command

        # depends_on: user-specified takes priority, otherwise use auto-detected
        if depends_on:
            service_def["depends_on"] = {
                dep: {"condition": "service_healthy"} for dep in depends_on
            }
        elif name in auto_deps:
            service_def["depends_on"] = {
                dep: {"condition": "service_healthy"} for dep in auto_deps[name]
            }

        # Parse user-specified volumes
        user_mount_paths = set()
        for v in volumes:
            if ":" in v:
                vol_name = v.split(":")[0]
                mount_path = v.split(":")[1]
                user_mount_paths.add(mount_path)
                if not vol_name.startswith("/") and not vol_name.startswith("."):
                    compose["volumes"][vol_name] = {"driver": "local"}
            service_def.setdefault("volumes", []).append(v)

        # Auto-add default persistence volumes for known service types
        # Only if user didn't already specify volumes for those mount points
        if svc_type and "volumes" in defaults:
            for vol_def in defaults["volumes"]:
                if vol_def["mount"] not in user_mount_paths:
                    vol_name = f"{name}_{vol_def['name']}" if not vol_def["name"].startswith(name) else vol_def["name"]
                    vol_mapping = f"{vol_name}:{vol_def['mount']}"
                    service_def.setdefault("volumes", []).append(vol_mapping)
                    compose["volumes"][vol_name] = {"driver": "local"}
                    compose_log.info(
                        f"Auto-added volume '{vol_name}' for {svc_type} data persistence ({vol_def['comment']})",
                        extra={"component": "compose.generate"},
                    )

        compose["services"][name] = service_def

    # Remove empty volumes key — a DevOps engineer never leaves empty sections
    if not compose["volumes"]:
        del compose["volumes"]

    output_path = COMPOSE_DIR / output_filename
    yaml_content = yaml.dump(compose, default_flow_style=False, sort_keys=False)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    compose_log.info(
        f"Generated compose file: {output_path}",
        extra={"component": "compose.generate"},
    )

    return (
        f"✓ Compose file generated at: {output_path}\n\n"
        f"Contents:\n```yaml\n{yaml_content}```"
    )


@tool
def compose_diff(file_path_old: str, file_path_new: str) -> str:
    """Show the differences between two Docker Compose files.

    Args:
        file_path_old: Path to the original compose file.
        file_path_new: Path to the new/modified compose file.

    Returns:
        Unified diff output showing changes.
    """
    import difflib

    compose_log.info(
        f"Diffing {file_path_old} vs {file_path_new}",
        extra={"component": "compose.diff"},
    )

    try:
        with open(file_path_old, "r") as f:
            old_lines = f.readlines()
        with open(file_path_new, "r") as f:
            new_lines = f.readlines()
    except FileNotFoundError as e:
        return f"ERROR: File not found: {e}"

    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=file_path_old, tofile=file_path_new,
        lineterm="",
    )
    diff_output = "\n".join(diff)

    if diff_output:
        return f"━━ COMPOSE DIFF ━━━━━━━━━━━━━━━━━━━━━━━\n{diff_output}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    else:
        return "No differences found — files are identical."


@tool
def backup_compose_file(file_path: str) -> str:
    """Create a timestamped backup of a Docker Compose file.

    Args:
        file_path: Path to the compose file to back up.

    Returns:
        Path to the backup file or error message.
    """
    compose_log.info(
        f"Backing up compose file: {file_path}",
        extra={"component": "compose.backup"},
    )

    if not os.path.exists(file_path):
        return f"ERROR: File not found: {file_path}"

    ist = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime.now(ist).strftime("%Y%m%d_%H%M%S")
    filename = Path(file_path).stem
    backup_name = f"{filename}_backup_{timestamp}.yml"
    backup_path = BACKUPS_DIR / backup_name

    try:
        shutil.copy2(file_path, backup_path)
        compose_log.info(
            f"Backup created: {backup_path}",
            extra={"component": "compose.backup"},
        )
        return f"✓ Backup created: {backup_path}"
    except Exception as e:
        log_exception(
            component="compose.backup",
            exc_type=type(e).__name__,
            message=str(e),
            input_data=f"file_path={file_path}",
            response="Backup failed",
            safe_state=True,
        )
        return f"ERROR: Failed to create backup: {e}"
