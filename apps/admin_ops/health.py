"""admin_ops_health() — System Health checks for platform operations itself.

Wired into ``apps.system_health.services.report()`` as ``data["adminOps"]``.
Same check shape as the other health modules: key, severity, component,
current_state, expected_state, last_check, owner, recommended_action,
resolution_link.

These checks watch the operations function for the failure modes that make it
silently stop working: an unowned critical incident, a ticket nobody triaged, a
maintenance template that stopped generating, an alert still firing for a
resolved defect — and the super-role grant itself, since a missing permission
would otherwise leave part of the platform silently inaccessible to Admin.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.admin_ops.models import (
    AdminOperationsWorkItem,
    IncidentStatus,
    MaintenanceTemplate,
    Severity,
    SupportTicket,
    SystemIncident,
    TicketStatus,
    WorkItemStatus,
)

# A ticket may reasonably sit unlooked-at for a working day, not a week.
TRIAGE_SLA_HOURS = 24
ACKNOWLEDGE_SLA_MINUTES = 60


def admin_ops_health() -> dict:
    now = timezone.now()
    return {
        "checks": [
            _unacknowledged_critical_incidents(now),
            _untriaged_tickets(now),
            _unowned_recurring_incidents(now),
            _overdue_admin_work(now),
            _stale_maintenance(now),
            _resolved_incidents_still_alerting(now),
            _admin_super_role_permissions(now),
        ]
    }


def _check(key, severity, component, current, expected, now, action, link) -> dict:
    return {
        "key": key,
        "severity": severity,
        "component": component,
        "current_state": current,
        "expected_state": expected,
        "last_check": now,
        "owner": "Platform/Ops",
        "recommended_action": action,
        "resolution_link": link,
    }


def _unacknowledged_critical_incidents(now) -> dict:
    cutoff = now - timedelta(minutes=ACKNOWLEDGE_SLA_MINUTES)
    stale = SystemIncident.objects.filter(
        severity=Severity.CRITICAL,
        status=IncidentStatus.OPEN,
        first_detected_at__lt=cutoff,
    ).count()
    return _check(
        "admin_ops_unacknowledged_critical",
        "critical" if stale else "ok",
        "Critical Incident Response",
        f"{stale} critical incident(s) open and unacknowledged for over "
        f"{ACKNOWLEDGE_SLA_MINUTES} minutes",
        "Every critical incident acknowledged within the hour",
        now,
        "Open the incident, acknowledge it, and begin investigation.",
        "/admin-ops/incidents?status=open",
    )


def _untriaged_tickets(now) -> dict:
    cutoff = now - timedelta(hours=TRIAGE_SLA_HOURS)
    stale = SupportTicket.objects.filter(
        status=TicketStatus.SUBMITTED, created_at__lt=cutoff
    ).count()
    return _check(
        "admin_ops_untriaged_tickets",
        "warning" if stale else "ok",
        "Support Triage",
        f"{stale} ticket(s) submitted over {TRIAGE_SLA_HOURS}h ago and not triaged",
        f"Every ticket triaged within {TRIAGE_SLA_HOURS}h",
        now,
        "Triage the queue: set severity, then schedule or backlog each ticket.",
        "/admin-ops/support?status=submitted",
    )


def _unowned_recurring_incidents(now) -> dict:
    """A defect firing repeatedly with nobody assigned is the classic
    disappearing incident — visible, counted, and nobody's job."""
    unowned = (
        SystemIncident.objects.exclude(
            status__in=[IncidentStatus.RESOLVED, IncidentStatus.CLOSED]
        )
        .filter(owner_id__isnull=True, occurrence_count__gte=5)
        .count()
    )
    return _check(
        "admin_ops_unowned_recurring_incidents",
        "warning" if unowned else "ok",
        "Incident Ownership",
        f"{unowned} incident(s) seen 5+ times with no owner",
        "Every recurring incident has an owner and a next action",
        now,
        "Acknowledge each recurring incident to take ownership of it.",
        "/admin-ops/incidents",
    )


def _overdue_admin_work(now) -> dict:
    overdue = AdminOperationsWorkItem.objects.filter(
        status__in=[
            WorkItemStatus.BACKLOG,
            WorkItemStatus.SCHEDULED,
            WorkItemStatus.IN_PROGRESS,
            WorkItemStatus.WAITING,
        ],
        due_date__lt=now.date(),
    ).count()
    return _check(
        "admin_ops_overdue_work",
        "warning" if overdue else "ok",
        "Admin Work Items",
        f"{overdue} work item(s) past their due date",
        "No platform work past its due date",
        now,
        "Reschedule or complete the overdue items in Admin My Plan.",
        "/admin-ops/my-plan",
    )


def _stale_maintenance(now) -> dict:
    """A template past due means the generation job is not running -- routine
    upkeep silently stops, which is exactly what the job exists to prevent."""
    overdue = MaintenanceTemplate.objects.filter(
        active=True, next_due_date__lt=now.date() - timedelta(days=1)
    ).count()
    return _check(
        "admin_ops_stale_maintenance",
        "warning" if overdue else "ok",
        "Maintenance Generation",
        f"{overdue} maintenance template(s) more than a day past due",
        "The generation job materialises every due template daily",
        now,
        "Check the admin_maintenance_generation job is running.",
        "/admin-ops/maintenance",
    )


def _resolved_incidents_still_alerting(now) -> dict:
    from apps.notifications.models import Notification

    resolved_ids = set(
        SystemIncident.objects.filter(
            status__in=[IncidentStatus.RESOLVED, IncidentStatus.CLOSED]
        ).values_list("id", flat=True)
    )
    stale = (
        Notification.objects.filter(
            source_event_type="admin_ops.incident.detected",
            context_id__in=resolved_ids,
            status="unread",
        ).count()
        if resolved_ids
        else 0
    )
    return _check(
        "admin_ops_resolved_still_alerting",
        "warning" if stale else "ok",
        "Notification Lifecycle",
        f"{stale} live notification(s) for incidents that are already resolved",
        "Resolving an incident closes its notifications",
        now,
        "Resolve through SystemIncidentService so the condition is closed too.",
        "/notifications",
    )


def _admin_super_role_permissions(now) -> dict:
    """Admin must receive every canonical permission, including new ones."""
    from apps.core.rbac import Permission, ROLE_PERMISSIONS, EdifyRole

    granted = set(ROLE_PERMISSIONS[EdifyRole.ADMIN])
    missing = sorted(p.value for p in Permission if p not in granted)
    return _check(
        "admin_ops_super_role_permissions",
        "critical" if missing else "ok",
        "Admin Super-role Permissions",
        f"Admin is missing {len(missing)} permission(s): {missing}"
        if missing
        else "Admin holds every canonical permission",
        "Admin holds every canonical permission",
        now,
        "Restore the complete Admin grant in apps/core/rbac.py.",
        "/admin-panel/roles-permissions",
    )
