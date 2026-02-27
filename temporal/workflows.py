"""
Temporal Workflows — durable, fault-tolerant DevOps workflows.

Workflows:
- DeployWorkflow         : Full deploy pipeline with auto-rollback
- HealthMonitorWorkflow  : Continuous health monitoring loop
- RollbackWorkflow       : Automated rollback to last backup
"""

import asyncio
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activity stubs (not actual implementations — Temporal handles routing)
with workflow.unsafe.imports_passed_through():
    from temporal.activities import (
        ComposeInput,
        TestInput,
        BackupInput,
        RollbackInput,
        HealthCheckResult,
    )


# ── Deploy Workflow ───────────────────────────────────
@workflow.defn(name="DeployWorkflow")
class DeployWorkflow:
    """Full deployment pipeline with automatic rollback on failure.

    Steps:
    1. Validate compose file
    2. Backup existing compose file
    3. Detect port conflicts
    4. Deploy services (compose up)
    5. Run 8-point test suite
    6. If tests fail → auto-rollback to backup
    7. Send notification with results
    """

    @workflow.run
    async def run(self, file_path: str) -> str:
        workflow.logger.info(f"DeployWorkflow started: {file_path}")

        results = []

        # Step 1: Validate
        workflow.logger.info("Step 1/6: Validating compose file")
        validation = await workflow.execute_activity(
            "validate_compose",
            file_path,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        results.append(f"[1/6] Validate: {validation[:100]}")

        if "ERROR" in validation or "FAILED" in validation:
            msg = f"DEPLOY ABORTED — Validation failed:\n{validation}"
            await self._notify(msg)
            return msg

        # Step 2: Backup
        workflow.logger.info("Step 2/6: Backing up compose file")
        backup_result = await workflow.execute_activity(
            "backup_compose",
            BackupInput(file_path=file_path),
            start_to_close_timeout=timedelta(seconds=30),
        )
        results.append(f"[2/6] Backup: {backup_result[:100]}")

        # Step 3: Port conflicts
        workflow.logger.info("Step 3/6: Checking port conflicts")
        conflicts = await workflow.execute_activity(
            "detect_conflicts",
            file_path,
            start_to_close_timeout=timedelta(seconds=30),
        )
        results.append(f"[3/6] Ports: {conflicts[:100]}")

        # Check for actual conflicts (⚠ or OCCUPIED), not just the report title
        has_real_conflicts = "OCCUPIED" in conflicts.upper() or "\u26a0" in conflicts
        if has_real_conflicts:
            msg = f"DEPLOY ABORTED — Port conflicts detected:\n{conflicts}"
            await self._notify(msg)
            return msg

        # Step 4: Deploy
        workflow.logger.info("Step 4/6: Deploying services")
        deploy_result = await workflow.execute_activity(
            "deploy_compose",
            ComposeInput(file_path=file_path),
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        results.append(f"[4/6] Deploy: {deploy_result[:100]}")

        if "FAILED" in deploy_result or "ERROR" in deploy_result:
            # Auto-rollback
            workflow.logger.warn("Deployment failed — triggering rollback")
            rollback = await workflow.execute_child_workflow(
                RollbackWorkflow.run,
                RollbackInput(current_file=file_path),
                id=f"rollback-{workflow.info().workflow_id}",
            )
            msg = f"DEPLOY FAILED — Auto-rollback triggered:\n{deploy_result}\n\nRollback result:\n{rollback}"
            await self._notify(msg)
            return msg

        # Step 5: Test suite
        workflow.logger.info("Step 5/6: Running post-deploy tests")
        test_result = await workflow.execute_activity(
            "run_tests",
            TestInput(file_path=file_path),
            start_to_close_timeout=timedelta(minutes=3),
            heartbeat_timeout=timedelta(seconds=120),
        )
        results.append(f"[5/6] Tests: {test_result[:200]}")

        if "FAIL" in test_result.upper() and "PASS" not in test_result.upper():
            # Tests failed — rollback
            workflow.logger.warn("Tests failed — triggering rollback")
            rollback = await workflow.execute_child_workflow(
                RollbackWorkflow.run,
                RollbackInput(current_file=file_path),
                id=f"rollback-{workflow.info().workflow_id}",
            )
            msg = f"DEPLOY FAILED (tests) — Auto-rollback triggered:\n{test_result}\n\nRollback:\n{rollback}"
            await self._notify(msg)
            return msg

        # Step 6: Success notification
        summary = "\n".join(results)
        msg = f"DEPLOYMENT SUCCESSFUL\n\n{summary}\n\nTest Results:\n{test_result}"
        await self._notify(msg)

        workflow.logger.info("DeployWorkflow completed successfully")
        return msg

    async def _notify(self, message: str):
        """Send a notification."""
        await workflow.execute_activity(
            "send_notification",
            message[:500],
            start_to_close_timeout=timedelta(seconds=10),
        )


# ── Health Monitor Workflow ───────────────────────────
@workflow.defn(name="HealthMonitorWorkflow")
class HealthMonitorWorkflow:
    """Continuous health monitoring workflow.

    Runs health checks every interval_seconds and:
    - Logs results
    - Sends alert if unhealthy containers detected
    - Optionally triggers AI analysis on failures

    Can run indefinitely — Temporal handles long-running workflows natively.
    """

    @workflow.run
    async def run(self, interval_seconds: int = 60) -> str:
        workflow.logger.info(f"HealthMonitorWorkflow started (interval={interval_seconds}s)")

        check_count = 0
        failure_count = 0
        max_checks = 1440  # 24 hours at 60s intervals

        while check_count < max_checks:
            check_count += 1
            workflow.logger.info(f"Health check #{check_count}")

            # Run health check
            result: HealthCheckResult = await workflow.execute_activity(
                "health_check",
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            if result.get("has_failures"):
                failure_count += 1
                workflow.logger.warn(f"Unhealthy containers detected (failure #{failure_count})")

                # Alert on first failure
                if failure_count == 1:
                    await workflow.execute_activity(
                        "send_notification",
                        f"HEALTH ALERT: Unhealthy containers detected!\n{result.get('report', '')[:300]}",
                        start_to_close_timeout=timedelta(seconds=10),
                    )

                # After 3 consecutive failures, trigger AI analysis
                if failure_count >= 3:
                    workflow.logger.warn("3+ consecutive failures — requesting AI analysis")
                    analysis = await workflow.execute_activity(
                        "agent_analyze",
                        f"Analyze these health check results and diagnose the issue:\n{result.get('report', '')}",
                        start_to_close_timeout=timedelta(minutes=2),
                    )
                    await workflow.execute_activity(
                        "send_notification",
                        f"AI DIAGNOSIS after {failure_count} failures:\n{analysis[:400]}",
                        start_to_close_timeout=timedelta(seconds=10),
                    )
                    failure_count = 0  # Reset after analysis
            else:
                failure_count = 0  # Reset on success

            # Sleep until next check (Temporal durable timer — survives restarts)
            await asyncio.sleep(interval_seconds)

        return f"HealthMonitorWorkflow completed: {check_count} checks performed"


# ── Rollback Workflow ─────────────────────────────────
@workflow.defn(name="RollbackWorkflow")
class RollbackWorkflow:
    """Automated rollback workflow.

    Steps:
    1. Tear down current (failed) deployment
    2. Find latest backup (or use specified backup)
    3. Deploy backup
    4. Run test suite on backup deployment
    5. Report result
    """

    @workflow.run
    async def run(self, input: RollbackInput) -> str:
        workflow.logger.info(f"RollbackWorkflow started: {input.current_file}")

        # Step 1: Tear down current
        workflow.logger.info("Rollback Step 1: Tearing down current deployment")
        teardown = await workflow.execute_activity(
            "teardown_compose",
            ComposeInput(file_path=input.current_file),
            start_to_close_timeout=timedelta(minutes=2),
        )

        # Step 2: Determine backup file
        backup_file = input.backup_file
        if not backup_file:
            # List containers to find the backup — use file path naming convention
            import os
            from pathlib import Path
            backup_dir = Path(input.current_file).parent.parent / "backups"
            if backup_dir.exists():
                backups = sorted(backup_dir.glob("*.yml"), key=lambda f: f.stat().st_mtime, reverse=True)
                if backups:
                    backup_file = str(backups[0])

        if not backup_file:
            msg = "ROLLBACK FAILED: No backup file found"
            await workflow.execute_activity(
                "send_notification", msg,
                start_to_close_timeout=timedelta(seconds=10),
            )
            return msg

        # Step 3: Deploy backup
        workflow.logger.info(f"Rollback Step 2: Deploying backup: {backup_file}")
        deploy = await workflow.execute_activity(
            "deploy_compose",
            ComposeInput(file_path=backup_file),
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(seconds=60),
        )

        # Step 4: Test
        workflow.logger.info("Rollback Step 3: Testing rollback deployment")
        tests = await workflow.execute_activity(
            "run_tests",
            TestInput(file_path=backup_file),
            start_to_close_timeout=timedelta(minutes=3),
        )

        # Step 5: Report
        if "FAIL" in tests.upper() and "PASS" not in tests.upper():
            msg = f"ROLLBACK CRITICAL: Backup deployment also failing!\nTeardown: {teardown[:100]}\nDeploy: {deploy[:100]}\nTests: {tests[:200]}"
        else:
            msg = f"ROLLBACK SUCCESSFUL\nBackup: {backup_file}\nTeardown: {teardown[:100]}\nDeploy: {deploy[:100]}\nTests: {tests[:100]}"

        await workflow.execute_activity(
            "send_notification", msg[:500],
            start_to_close_timeout=timedelta(seconds=10),
        )

        workflow.logger.info("RollbackWorkflow completed")
        return msg


# ── All workflows registry ────────────────────────────
ALL_WORKFLOWS = [
    DeployWorkflow,
    HealthMonitorWorkflow,
    RollbackWorkflow,
]
