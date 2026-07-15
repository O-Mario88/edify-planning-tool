"""Notifications service — per-user notification rail and workflow routing."""

from __future__ import annotations

from django.utils import timezone
from .models import Notification


class NotificationLinkResolver:
    @staticmethod
    def resolve(
        event_type: str, context_type: str | None, context_id: str | None, role: str
    ) -> tuple[str, str]:
        """
        Resolves target_route and action_label based on the event, context, and recipient's active role.
        This prevents role leakage by directing different roles to different pages for the same event.
        """
        route = "/dashboard"
        label = "View Dashboard"

        role = (role or "Staff").lower()

        if event_type == "critical_school_ssa":
            if role in ("cceo", "partnerfieldofficer"):
                route = "/planning"
                label = "Open Planning"
            elif role == "projectleader":
                route = "/my-team"
                label = "View Team Portfolio"
            elif role in ("countrydirector", "regionalvicepresident"):
                route = "/analytics"
                label = "Country Insights"
            elif role == "impactassessment":
                route = "/ia/dashboard/"
                label = "SSA Verification"
            elif role == "humanresources":
                route = "/dashboard"
                label = "View Performance Risks"

        elif event_type == "partner_scheduled_activity":
            if role == "partnerfieldofficer":
                route = "/my-plan"
                label = "Partner My Plan"
            elif role == "cceo":
                route = "/my-plan"
                label = "Staff My Plan"
            elif role == "projectleader":
                route = "/my-team"
                label = "Monitoring Dashboard"

        elif event_type == "evidence_returned":
            if role in ("cceo", "partnerfieldofficer"):
                route = "/my-plan"
                label = "Fix Evidence"
            elif role == "projectleader":
                route = "/my-team"
                label = "Review Evidence"
            elif role == "impactassessment":
                route = "/ia/dashboard/"
                label = "Evidence Verification"

        elif event_type == "fund_request_approved":
            if role == "accountant":
                route = "/fund-requests"
                label = "Disburse Funds"
            else:
                route = "/fund-requests"
                label = "View Fund Request"

        elif event_type == "leave_requested":
            route = "/leave/approvals"
            label = "Review Leave Request"

        elif event_type == "leave_approved":
            route = "/personal-time-off/"
            label = "View Leave Request"

        elif event_type == "leave_rejected":
            route = "/personal-time-off/"
            label = "View Leave Status"

        elif event_type == "leave_returned":
            route = "/personal-time-off/"
            label = "Update Leave Request"

        elif event_type == "account_lockout":
            route = f"/admin-panel/users/{context_id}"
            label = "Unlock Account"

        elif event_type == "core_school_assigned":
            route = "/schools"
            label = "Open School"

        elif event_type == "activity_closed":
            route = "/my-plan"
            label = "Open Activity"

        elif event_type in (
            "field_debrief_routed",
            "field_debrief_clarification_requested",
            "field_debrief_clarification_response",
            "field_debrief_recommendation_reviewed",
            "field_debrief_action_update",
            "field_debrief_peer_solution",
            "field_debrief_peer_solution_endorsed",
            "field_debrief_peer_solution_classified",
            "field_debrief_recurring_issue",
        ):
            # All of these route to the debrief's own detail page — context_id
            # is always the DailyDebrief id for these events (see
            # apps/debriefs/field_debrief_service.py, peer_solution_service.py,
            # action_service.py, insight_service.py).
            route = f"/debriefs/{context_id}"
            label = "Open Debrief"

        elif event_type == "field_debrief_recurring_issue_escalated":
            # context_id is a DailyDebriefInsight id — there is no per-insight
            # detail page, so this links to the Field Debrief Dashboard where
            # "Debrief Intelligence Highlights" surfaces open insights.
            route = "/debriefs"
            label = "View Recurring Field Issues"

        elif context_type == "School":
            route = "/schools"
            label = "Open School"
        elif context_type == "Cluster":
            route = "/clusters"
            label = "Open Cluster"
        elif context_type == "Activity":
            route = "/my-plan"
            label = "Open Activity"
        elif context_type == "Message":
            route = f"/messages/{context_id}"
            label = "Open Chat"

        return route, label


class WorkflowNotificationService:
    @staticmethod
    def trigger(
        event_type: str,
        category: str,
        priority: str,
        title: str,
        body: str,
        context_type: str | None = None,
        context_id: str | None = None,
        recipients=None,
    ) -> list[Notification]:
        """
        Triggers a workflow event. For each recipient, it verifies access,
        resolves the role-specific route and action label, and saves the Notification.
        """
        from apps.accounts.models import User
        from apps.notifications.models import Notification

        created_notifications = []
        if not recipients:
            return created_notifications

        # Standardize querysets / IDs
        recipient_list = []
        if hasattr(recipients, "iterator"):
            recipient_list = list(recipients)
        elif isinstance(recipients, list):
            recipient_list = recipients
        else:
            recipient_list = [recipients]

        for r in recipient_list:
            user_obj = None
            if isinstance(r, User):
                user_obj = r
                user_id = r.id
            else:
                user_id = str(r)
                user_obj = User.objects.filter(id=user_id).first()

            if not user_obj:
                continue

            role = getattr(user_obj, "active_role", None) or "Staff"
            target_route, action_label = NotificationLinkResolver.resolve(
                event_type, context_type, context_id, role
            )

            notif = Notification.objects.create(
                recipient_id=user_id,
                recipient_role=role,
                title=title,
                body=body,
                category=category,
                context_type=context_type,
                context_id=context_id,
                target_route=target_route,
                action_label=action_label,
                priority=priority,
                source_event_type=event_type,
                source_event_id=context_id or "",
                action_required=priority in ("high", "urgent"),
            )
            created_notifications.append(notif)

        return created_notifications


def recent(principal) -> list[dict]:
    qs = Notification.objects.filter(recipient_id=principal.user_id).order_by(
        "-created_at"
    )[:50]
    return [_serialize(n) for n in qs]


def rail(principal) -> list[dict]:
    """The notification rail (unread + recent read, capped)."""
    qs = Notification.objects.filter(recipient_id=principal.user_id).order_by(
        "-created_at"
    )[:20]
    return [_serialize(n) for n in qs]


def counts(principal) -> dict:
    base = Notification.objects.filter(recipient_id=principal.user_id)
    return {"unread": base.filter(status="unread").count(), "total": base.count()}


def unread_count(principal) -> dict:
    return {
        "count": Notification.objects.filter(
            recipient_id=principal.user_id, status="unread"
        ).count()
    }


def mark_read(notification_id: str, principal) -> dict:
    n = Notification.objects.filter(
        id=notification_id, recipient_id=principal.user_id
    ).first()
    if n:
        n.status = "read"
        n.read_at = timezone.now()
        n.save(update_fields=["status", "read_at"])
    return {"ok": True}


def mark_all_read(principal) -> dict:
    Notification.objects.filter(recipient_id=principal.user_id, status="unread").update(
        status="read", read_at=timezone.now()
    )
    return {"ok": True}


def resolve(notification_id: str, principal) -> dict:
    n = Notification.objects.filter(
        id=notification_id, recipient_id=principal.user_id
    ).first()
    if n:
        n.status = "archived"
        n.save(update_fields=["status"])
    return {"ok": True}


def _serialize(n: Notification) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "body": n.body,
        "priority": n.priority,
        "actionRequired": n.action_required,
        "actionLabel": n.action_label,
        "contextType": n.context_type,
        "contextId": n.context_id,
        "category": n.category,
        "targetRoute": n.target_route,
        "status": n.status,
        "sourceEventType": n.source_event_type,
        "createdAt": n.created_at.isoformat(),
    }
