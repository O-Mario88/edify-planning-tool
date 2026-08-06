"""background_automation_health() — System Health checks for the scheduler
and every registered periodic job (Issue 2 / §9 observability requirements).

Each check returns the full required shape: severity, component, current
state, expected state, last check, owner, recommended action, and a direct
resolution link where one exists. Wired into apps.system_health.services
.report() as data["backgroundAutomation"].
"""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from apps.realtime.registry import SchedulerHealthService


def background_automation_health() -> dict:
    checks = []
    now = timezone.now()
    enabled = bool(getattr(settings, "ENABLE_BACKGROUND_JOBS", False))
    is_production = bool(getattr(settings, "IS_PRODUCTION", False))

    # ── 1. Is the scheduler enabled at all on THIS process' config ──────────
    checks.append(
        {
            "key": "scheduler_enabled",
            "severity": "ok"
            if enabled
            else ("critical" if is_production else "warning"),
            "component": "Scheduler",
            "current_state": "Enabled"
            if enabled
            else "Disabled (ENABLE_BACKGROUND_JOBS=false)",
            "expected_state": "Enabled in production",
            "last_check": now,
            "owner": "Platform/Ops",
            "recommended_action": (
                "OK"
                if enabled
                else "Provision the dedicated worker process (see docs/scheduler-deployment.md) "
                "and set ENABLE_BACKGROUND_JOBS=true on it."
            ),
            "resolution_link": "/system-health",
        }
    )

    if not enabled:
        # Nothing else is meaningful to check if jobs are off everywhere.
        return {"checks": checks}

    # ── 2. Scheduler process heartbeat ───────────────────────────────────────
    alive = SchedulerHealthService.is_scheduler_process_alive()
    checks.append(
        {
            "key": "scheduler_heartbeat",
            "severity": "ok" if alive else "critical",
            "component": "Scheduler",
            "current_state": "Recent job activity observed"
            if alive
            else "No job has started recently",
            "expected_state": "At least one job runs within every 10-minute window",
            "last_check": now,
            "owner": "Platform/Ops",
            "recommended_action": "OK"
            if alive
            else "Check the worker process is running (`python manage.py runscheduler`).",
            "resolution_link": "/system-health",
        }
    )

    # ── 3. Per-job health (overdue / failed / never run / duplicate) ────────
    for j in SchedulerHealthService.all_jobs_health():
        spec = j["spec"]
        label = spec.description if spec else j["job_name"]
        if j["severity"] == "ok":
            current = f"Last successful run: {j['last_successful']}"
        elif j["status"] == "never_run":
            current = "Never run"
        elif j["status"] == "failed":
            current = f"Last run FAILED: {j['last_error']}"
        else:
            current = f"Overdue — last successful run: {j['last_successful']}"
        checks.append(
            {
                "key": f"job_{j['job_name']}",
                "severity": j["severity"],
                "component": f"Scheduled Job: {j['job_name']}",
                "current_state": current,
                "expected_state": f"{label} ({spec.cron if spec else '?'})",
                "last_check": now,
                "owner": "Platform/Ops",
                "recommended_action": (
                    "OK"
                    if j["severity"] == "ok"
                    else f"Run `python manage.py scheduler_health_check` and inspect ScheduledJobExecution "
                    f"rows for '{j['job_name']}'."
                ),
                "resolution_link": "/system-health",
            }
        )

    return {"checks": checks}
