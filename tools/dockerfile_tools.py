"""
Dockerfile analysis and linting tool for the Strands DevOps Agent.

Tools:
- analyze_dockerfile : Parse and lint a Dockerfile for best-practice violations
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strands import tool
from utils.logger import get_logger

agent_log = get_logger("agent")


# ── Linting Rules ─────────────────────────────────────
RULES = [
    {
        "id": "DF001",
        "severity": "HIGH",
        "name": "Running as root",
        "check": lambda lines: not any(
            l.strip().upper().startswith("USER")
            for l in lines if l.strip() and not l.strip().startswith("#")
        ),
        "message": "No USER instruction found — container will run as root. Add 'USER nonroot' after installing dependencies.",
    },
    {
        "id": "DF002",
        "severity": "HIGH",
        "name": "No HEALTHCHECK",
        "check": lambda lines: not any(
            l.strip().upper().startswith("HEALTHCHECK")
            for l in lines if l.strip() and not l.strip().startswith("#")
        ),
        "message": "No HEALTHCHECK defined. Add one to enable Docker health monitoring.",
    },
    {
        "id": "DF003",
        "severity": "MEDIUM",
        "name": "Using :latest tag",
        "check": lambda lines: any(
            (
                re.search(r"FROM\s+\S+:latest", l, re.IGNORECASE)
                or (
                    re.match(r"^FROM\s+\S+\s*$", l.strip(), re.IGNORECASE)
                    and ":" not in l.strip().split()[-1]
                    and "scratch" not in l.lower()
                )
            )
            for l in lines
            if l.strip().upper().startswith("FROM") and not l.strip().startswith("#")
        ),
        "message": "Using :latest or untagged base image. Pin to a specific version for reproducible builds (e.g. python:3.11-slim).",
    },
    {
        "id": "DF004",
        "severity": "MEDIUM",
        "name": "Too many RUN layers",
        "check": lambda lines: sum(
            1 for l in lines
            if l.strip().upper().startswith("RUN") and not l.strip().startswith("#")
        ) > 10,
        "message": "More than 10 RUN instructions. Chain commands with '&&' to reduce image layers and size.",
    },
    {
        "id": "DF005",
        "severity": "HIGH",
        "name": "Secrets in ENV",
        "check": lambda lines: any(
            re.search(
                r"(PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY)\s*=\s*\S+",
                l, re.IGNORECASE,
            )
            for l in lines
            if l.strip().upper().startswith("ENV") and not l.strip().startswith("#")
        ),
        "message": "Hardcoded secrets detected in ENV. Use build args, .env files, or Docker secrets instead.",
    },
    {
        "id": "DF006",
        "severity": "LOW",
        "name": "No .dockerignore hint",
        "check": lambda lines: any(
            l.strip().upper().startswith("COPY .") or l.strip().upper().startswith("ADD .")
            for l in lines if not l.strip().startswith("#")
        ),
        "message": "Using 'COPY .' or 'ADD .' — ensure a .dockerignore exists to exclude node_modules, .git, __pycache__, etc.",
    },
    {
        "id": "DF007",
        "severity": "MEDIUM",
        "name": "Using ADD instead of COPY",
        "check": lambda lines: any(
            l.strip().upper().startswith("ADD")
            and not any(x in l for x in [".tar", ".gz", "http://", "https://"])
            for l in lines if not l.strip().startswith("#")
        ),
        "message": "Using ADD for simple file copy. Use COPY instead — ADD has implicit tar extraction that can be unexpected.",
    },
    {
        "id": "DF008",
        "severity": "LOW",
        "name": "No LABEL/maintainer",
        "check": lambda lines: not any(
            l.strip().upper().startswith("LABEL") or l.strip().upper().startswith("MAINTAINER")
            for l in lines if not l.strip().startswith("#")
        ),
        "message": "No LABEL or MAINTAINER found. Add labels for traceability (maintainer, version, description).",
    },
    {
        "id": "DF009",
        "severity": "MEDIUM",
        "name": "apt-get without cleanup",
        "check": lambda lines: any(
            "apt-get install" in l and "rm -rf /var/lib/apt/lists" not in l
            for l in lines
            if l.strip().upper().startswith("RUN") and not l.strip().startswith("#")
        ),
        "message": "apt-get install without cleanup. Add '&& rm -rf /var/lib/apt/lists/*' to reduce image size by 50-200MB.",
    },
    {
        "id": "DF010",
        "severity": "LOW",
        "name": "No WORKDIR set",
        "check": lambda lines: not any(
            l.strip().upper().startswith("WORKDIR")
            for l in lines if not l.strip().startswith("#")
        ),
        "message": "No WORKDIR defined. Files will be added to /. Set a working directory for clarity (e.g. WORKDIR /app).",
    },
    {
        "id": "DF011",
        "severity": "MEDIUM",
        "name": "EXPOSE missing",
        "check": lambda lines: not any(
            l.strip().upper().startswith("EXPOSE")
            for l in lines if not l.strip().startswith("#")
        ),
        "message": "No EXPOSE instruction. Document the port(s) this container listens on.",
    },
    {
        "id": "DF012",
        "severity": "HIGH",
        "name": "Using root in final stage",
        "check": lambda lines: _check_root_final_stage(lines),
        "message": "The final stage runs as root. Always drop privileges with USER in the last stage.",
    },
]


def _check_root_final_stage(lines: list[str]) -> bool:
    """Check if the final build stage has no USER instruction."""
    # Find the last FROM line (start of final stage)
    last_from_idx = -1
    for i, l in enumerate(lines):
        if l.strip().upper().startswith("FROM") and not l.strip().startswith("#"):
            last_from_idx = i

    if last_from_idx == -1:
        return False

    # Check if any USER instruction exists after the last FROM
    for l in lines[last_from_idx:]:
        if l.strip().upper().startswith("USER") and not l.strip().startswith("#"):
            return False
    return True


@tool
def analyze_dockerfile(dockerfile_path: str) -> str:
    """Analyze a Dockerfile for best-practice violations and security issues.

    Checks 12 rules covering:
    - Security: running as root, hardcoded secrets, privilege escalation
    - Performance: too many layers, missing cleanup, ADD vs COPY
    - Standards: missing HEALTHCHECK, EXPOSE, LABEL, WORKDIR
    - Reproducibility: unpinned base images (:latest)

    Each finding includes severity (HIGH/MEDIUM/LOW) and a fix recommendation.
    Outputs a score from 0-100 with a letter grade.

    Args:
        dockerfile_path: Path to the Dockerfile to analyze.

    Returns:
        Analysis report with findings, severity, recommendations, and score.
    """
    agent_log.info(
        f"Analyzing Dockerfile: {dockerfile_path}",
        extra={"component": "dockerfile.analyze"},
    )

    if not os.path.exists(dockerfile_path):
        return f"ERROR: Dockerfile not found: {dockerfile_path}"

    with open(dockerfile_path, "r", encoding="utf-8") as f:
        content = f.read()
    lines = content.split("\n")

    # Parse basic info
    from_lines = [
        l.strip() for l in lines
        if l.strip().upper().startswith("FROM") and not l.strip().startswith("#")
    ]
    total_lines = len([l for l in lines if l.strip() and not l.strip().startswith("#")])
    stages = len(from_lines)
    run_count = sum(
        1 for l in lines
        if l.strip().upper().startswith("RUN") and not l.strip().startswith("#")
    )

    report = []
    report.append("DOCKERFILE ANALYSIS")
    report.append("=" * 50)
    report.append(f"  File   : {dockerfile_path}")
    report.append(f"  Lines  : {total_lines} (non-empty, non-comment)")
    report.append(f"  Stages : {stages} ({'multi-stage build' if stages > 1 else 'single-stage'})")
    report.append(f"  Base   : {', '.join(from_lines)}")
    report.append(f"  RUN    : {run_count} layer(s)")

    # Run checks
    findings = []
    for rule in RULES:
        try:
            if rule["check"](lines):
                findings.append(rule)
        except Exception:
            pass

    high = [f for f in findings if f["severity"] == "HIGH"]
    medium = [f for f in findings if f["severity"] == "MEDIUM"]
    low = [f for f in findings if f["severity"] == "LOW"]

    report.append("")
    report.append(f"FINDINGS: {len(high)} HIGH / {len(medium)} MEDIUM / {len(low)} LOW")
    report.append("-" * 50)

    severity_icon = {"HIGH": "[!!]", "MEDIUM": "[! ]", "LOW": "[i ]"}

    for f in findings:
        icon = severity_icon.get(f["severity"], "[? ]")
        report.append(f"")
        report.append(f"  {icon} {f['severity']} | {f['id']}: {f['name']}")
        report.append(f"      Fix: {f['message']}")

    if not findings:
        report.append("")
        report.append("  No issues found — Dockerfile follows best practices!")

    # Score
    score = max(0, 100 - (len(high) * 20) - (len(medium) * 10) - (len(low) * 5))

    report.append("")
    report.append("=" * 50)
    report.append(f"  SCORE: {score}/100")

    if score >= 80:
        report.append("  Grade: A — Production ready")
    elif score >= 60:
        report.append("  Grade: B — Good, but address HIGH findings before deploying")
    elif score >= 40:
        report.append("  Grade: C — Needs improvement, several issues to fix")
    else:
        report.append("  Grade: D — Significant issues, do NOT deploy as-is")

    report.append("=" * 50)

    full_report = "\n".join(report)
    agent_log.info(
        f"Dockerfile analysis complete: score={score}, findings={len(findings)}",
        extra={"component": "dockerfile.analyze"},
    )

    return full_report
