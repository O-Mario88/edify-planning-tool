"""school_action_health() — is the unassigned-action queue actually working?

Wired into apps.system_health.services.report() as data["schoolActions"].

This system has three ways to fail quietly, and each one looks fine from a
dashboard:

  1. **The sweep stops running.** Actions stay open after the work is done,
     the queue looks busy, and nobody can tell the difference between "still
     needed" and "nobody swept".
  2. **The queue is cleared by hand.** Resolutions accumulate with
     resolved_by_system=False, which means somebody asserted the work was done
     rather than the record proving it.
  3. **Sent and forgotten.** Actions pile up past their due date with no
     escalation, so delegating becomes a way of making a problem disappear
     from your own screen.

Each check below names one of those. Same shape as the other health modules:
key, severity, component, current_state, expected_state, last_check, owner,
recommended_action, resolution_link.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

# An action open well past its due date is a delegation that failed. A handful
# is normal operational slack; a pile means the loop is not being closed.
STALE_OVERDUE_DAYS = 14
OVERDUE_WARNING = 5
OVERDUE_CRITICAL = 20
# If most resolutions are manual, the auto-resolution path is either broken or
# being bypassed. Below this share, say so.
AUTO_RESOLVE_FLOOR = 0.6
# The sweep runs hourly; two missed runs is a scheduler problem, not a blip.
SWEEP_STALE_HOURS = 3


def school_action_health() -> dict:
    now = timezone.now()
    return {
        "checks": [
            _sweep_running_check(now),
            _overdue_backlog_check(now),
            _manual_resolution_check(now),
            _orphaned_recipient_check(now),
        ]
    }


def _sweep_running_check(now) -> dict:
    """Has the hourly sweep actually run?

    Without it nothing auto-resolves, and the queue silently reverts to the
    permanent list of unresolved problems this system replaced.
    """
    from apps.realtime.models import ScheduledJobExecution

    last = (
        ScheduledJobExecution.objects.filter(job_name="school_action_sweep")
        .order_by("-started_at")
        .first()
    )
    if not last:
        severity = "warning"
        state = "The sweep has never run"
    else:
        age = now - last.started_at
        hours = age.total_seconds() / 3600
        if hours > SWEEP_STALE_HOURS:
            severity = "critical"
        else:
            severity = "ok"
        state = f"Last run {last.started_at:%-d %b %H:%M} ({hours:.1f}h ago)"

    return {
        "key": "school_action_sweep_running",
        "severity": severity,
        "component": "School Action Queue",
        "current_state": state,
        "expected_state": (
            f"Run within the last {SWEEP_STALE_HOURS}h — it is what closes "
            "actions when the work is done"
        ),
        "last_check": now,
        "owner": "Admin",
        "recommended_action": (
            "OK"
            if severity == "ok"
            else "Check the runscheduler process and ENABLE_BACKGROUND_JOBS. "
            "Catch up with `python manage.py sweep_school_actions --apply`."
        ),
        "resolution_link": "/system-health",
    }


def _overdue_backlog_check(now) -> dict:
    """Actions long past due with nobody escalating."""
    from apps.planning.action_models import ACTIVE_STATES, ActionState, TeamAction

    cutoff = timezone.localdate() - timedelta(days=STALE_OVERDUE_DAYS)
    stale = TeamAction.objects.filter(
        state__in=ACTIVE_STATES, due_date__lt=cutoff
    ).exclude(state=ActionState.ESCALATED)
    count = stale.count()

    if count >= OVERDUE_CRITICAL:
        severity = "critical"
    elif count >= OVERDUE_WARNING:
        severity = "warning"
    else:
        severity = "ok"

    return {
        "key": "school_action_stale_overdue",
        "severity": severity,
        "component": "School Action Queue",
        "current_state": (
            f"{count} action(s) more than {STALE_OVERDUE_DAYS} days past due "
            "and not escalated"
        ),
        "expected_state": (
            f"Below {OVERDUE_WARNING} — delegating a school issue and never "
            "chasing it is how a problem disappears from a screen without "
            "being solved"
        ),
        "last_check": now,
        "owner": "PL/IA",
        "recommended_action": (
            "OK"
            if severity == "ok"
            else "Review /actions/sent (Overdue tab) and escalate or cancel "
            "what is no longer real."
        ),
        "resolution_link": "/actions/sent?tab=overdue",
    }


def _manual_resolution_check(now) -> dict:
    """Is the queue draining because work got done, or because people closed rows?"""
    from apps.planning.action_models import ActionState, TeamAction

    since = now - timedelta(days=30)
    resolved = TeamAction.objects.filter(
        state=ActionState.RESOLVED, resolved_at__gte=since
    )
    total = resolved.count()
    auto = resolved.filter(resolved_by_system=True).count()

    if total == 0:
        # Nothing resolved in a month is not itself a defect — a small
        # deployment may genuinely have none — so this reports rather than alarms.
        return {
            "key": "school_action_resolution_provenance",
            "severity": "ok",
            "component": "School Action Queue",
            "current_state": "No actions resolved in the last 30 days",
            "expected_state": "Resolutions confirmed by the record, not asserted",
            "last_check": now,
            "owner": "PL/IA",
            "recommended_action": "OK",
            "resolution_link": "/actions/sent?tab=resolved",
        }

    share = auto / total
    severity = "ok" if share >= AUTO_RESOLVE_FLOOR else "warning"
    return {
        "key": "school_action_resolution_provenance",
        "severity": severity,
        "component": "School Action Queue",
        "current_state": (
            f"{auto} of {total} resolutions ({share:.0%}) were confirmed by the "
            "record"
        ),
        "expected_state": (
            f"At least {AUTO_RESOLVE_FLOOR:.0%} auto-confirmed — a queue draining "
            "by hand is being cleared, not worked"
        ),
        "last_check": now,
        "owner": "PL/IA",
        "recommended_action": (
            "OK"
            if severity == "ok"
            else "Check which issue types are being closed manually — either "
            "the condition check is wrong or the queue is being tidied."
        ),
        "resolution_link": "/actions/sent?tab=resolved",
    }


def _orphaned_recipient_check(now) -> dict:
    """Actions whose recipient no longer has an account, or is deactivated.

    Nobody is going to do this work, and nothing else would notice: the row
    stays open forever holding its condition off the unassigned queue, so the
    school is invisible in both places at once.
    """
    from apps.accounts.models import User
    from apps.planning.action_models import ACTIVE_STATES, TeamAction

    active = TeamAction.objects.filter(state__in=ACTIVE_STATES)
    recipient_ids = set(active.values_list("recipient_id", flat=True))
    if not recipient_ids:
        count = 0
    else:
        live = set(
            User.objects.filter(id__in=recipient_ids, is_active=True).values_list(
                "id", flat=True
            )
        )
        count = len(recipient_ids - live)

    return {
        "key": "school_action_orphaned_recipient",
        "severity": "ok" if count == 0 else "critical",
        "component": "School Action Queue",
        "current_state": f"{count} active action(s) assigned to an inactive account",
        "expected_state": (
            "None — such an action holds its school off the unassigned queue "
            "while nobody is going to act on it"
        ),
        "last_check": now,
        "owner": "Admin",
        "recommended_action": (
            "OK"
            if count == 0
            else "Cancel or reassign these actions so their schools return to "
            "the urgent queue."
        ),
        "resolution_link": "/actions/sent",
    }
