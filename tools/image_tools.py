"""
Docker image management tools for the Strands DevOps Agent.

Tools:
- list_images    : List all local Docker images
- pull_image     : Pull an image from a registry
- remove_image   : Remove a local image
- image_history  : Show image layer history
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strands import tool
from utils.logger import get_logger, log_exception

agent_log = get_logger("agent")


def _run_cmd(cmd: list[str], component: str = "image", timeout: int = 300) -> dict:
    """Execute a command and return structured result."""
    full_cmd = " ".join(cmd)
    agent_log.info(f"Executing: {full_cmd}", extra={"component": component})
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=True)
        agent_log.info(f"Command completed: returncode={result.returncode}", extra={"component": component})
        return {"success": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except subprocess.TimeoutExpired:
        log_exception(component, "TimeoutExpired", f"Command timed out: {full_cmd}", full_cmd, "Aborted", True)
        return {"success": False, "stdout": "", "stderr": "Command timed out"}
    except Exception as e:
        log_exception(component, type(e).__name__, str(e), full_cmd, "Halted", True)
        return {"success": False, "stdout": "", "stderr": str(e)}


@tool
def list_images(show_all: bool = False) -> str:
    """List all locally available Docker images with their tags, sizes, and creation dates.

    Args:
        show_all: If True, show intermediate images too. Defaults to False.

    Returns:
        Formatted table of images or error message.
    """
    agent_log.info(f"Listing images (all={show_all})", extra={"component": "image.list"})

    cmd = ["docker", "images", "--format", "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}"]
    if show_all:
        cmd.insert(2, "-a")

    result = _run_cmd(cmd, "image.list")

    if result["success"]:
        return result["stdout"] if result["stdout"] else "No images found."
    else:
        return f"ERROR: Failed to list images.\n{result['stderr']}"


@tool
def pull_image(image_name: str) -> str:
    """Pull a Docker image from a registry.

    Args:
        image_name: Full image name with optional tag (e.g. 'nginx:latest', 'postgres:15').

    Returns:
        Pull result or error message.
    """
    agent_log.info(f"Pulling image: {image_name}", extra={"component": "image.pull"})

    if ":" not in image_name or image_name.endswith(":latest"):
        agent_log.warning(
            f"Pulling '{image_name}' -- using :latest tag is discouraged in production",
            extra={"component": "image.pull"},
        )

    cmd = ["docker", "pull", image_name]
    result = _run_cmd(cmd, "image.pull", timeout=600)

    if result["success"]:
        agent_log.info(f"Image '{image_name}' pulled successfully", extra={"component": "image.pull"})
        size_cmd = ["docker", "images", image_name, "--format", "{{.Size}}"]
        size_result = _run_cmd(size_cmd, "image.pull")
        size = size_result["stdout"] if size_result["success"] else "unknown"
        return f"Image '{image_name}' pulled successfully. Size: {size}\n{result['stdout']}"
    else:
        return f"ERROR: Failed to pull '{image_name}'.\n{result['stderr']}"


@tool
def remove_image(image_name: str, force: bool = False) -> str:
    """Remove a local Docker image.

    Args:
        image_name: Image name, tag, or ID to remove.
        force: If True, force removal even if in use. Defaults to False.

    Returns:
        Removal result or error message.
    """
    agent_log.info(f"Removing image: {image_name} (force={force})", extra={"component": "image.remove"})

    cmd = ["docker", "rmi", image_name]
    if force:
        cmd.insert(2, "-f")

    result = _run_cmd(cmd, "image.remove")

    if result["success"]:
        agent_log.info(f"Image '{image_name}' removed", extra={"component": "image.remove"})
        return f"Image '{image_name}' removed.\n{result['stdout']}"
    else:
        return f"ERROR: Failed to remove '{image_name}'.\n{result['stderr']}"


@tool
def image_history(image_name: str) -> str:
    """Show the layer history of a Docker image, including each layer's command and size.

    Useful for debugging image size, understanding build cache, and optimizing Dockerfiles.

    Args:
        image_name: Image name or ID to inspect.

    Returns:
        Layer history table or error message.
    """
    agent_log.info(f"Getting history for: {image_name}", extra={"component": "image.history"})

    cmd = ["docker", "history", "--format", "table {{.CreatedBy}}\t{{.Size}}\t{{.CreatedSince}}", image_name]
    result = _run_cmd(cmd, "image.history")

    if result["success"]:
        return f"IMAGE HISTORY: {image_name}\n{result['stdout']}"
    else:
        return f"ERROR: Failed to get history for '{image_name}'.\n{result['stderr']}"
