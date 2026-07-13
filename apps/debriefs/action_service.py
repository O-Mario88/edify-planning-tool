"""DebriefActionRoutingService — leadership actions created from a debrief
issue (§12). A debrief's own status and its actions' statuses are
independent: a debrief can stay "submitted" while several actions are open.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden

from .field_debrief_service import FieldDebriefService
from .models import DailyDebriefAction, DebriefActionStatus, DebriefStatus

# Who may create/manage actions — the read-scoped leadership roles (§4).
ACTION_MANAGER_ROLES = (
    "Program Lead", "CountryDirector", "HumanResources", "ImpactAssessment",
    "RegionalVicePresident", "Admin",
)

TERMINAL_STATUSES = (DebriefActionStatus.RESOLVED, DebriefActionStatus.CLOSED)


class DebriefActionRoutingService:
    @staticmethod
    def create(principal, debrief_id: str, *, issue: str, action: str, owner_user_id: str,
               priority: str = "medium", due_date=None) -> DailyDebriefAction:
        role = getattr(principal, "active_role", "")
        if role not in ACTION_MANAGER_ROLES:
            raise Forbidden("Your role cannot create a leadership action.")
        debrief = FieldDebriefService.get_one(principal, debrief_id)
        if not issue or not action or not owner_user_id:
            raise BadRequest("Issue, action, and owner are required.")

        record = DailyDebriefAction.objects.create(
            debrief=debrief, issue=issue, action=action, owner_user_id=owner_user_id,
            assigned_by_user_id=principal.user_id, priority=priority or "medium",
            due_date=due_date, status=DebriefActionStatus.ASSIGNED,
        )
        if debrief.status not in (DebriefStatus.RESTRICTED_INCIDENT,):
            debrief.status = DebriefStatus.ACTION_REQUIRED
            debrief.save(update_fields=["status"])
        DebriefActionRoutingService._notify(record, "Leadership action assigned to you", record.action)
        return record

    @staticmethod
    def update_status(principal, action_id: str, *, status: str, note: str = "") -> DailyDebriefAction:
        record = DailyDebriefAction.objects.filter(id=action_id).select_related("debrief").first()
        if not record:
            raise BadRequest("Action not found.")
        role = getattr(principal, "active_role", "")
        is_owner = record.owner_user_id == principal.user_id
        is_manager = role in ACTION_MANAGER_ROLES
        if not (is_owner or is_manager):
            raise Forbidden("You are not the owner or a manager of this action.")
        if status not in DebriefActionStatus.values:
            raise BadRequest("Unknown status.")

        with transaction.atomic():
            record.status = status
            if status in TERMINAL_STATUSES:
                record.resolution = note or record.resolution
                record.resolved_by_user_id = principal.user_id
                record.resolved_at = timezone.now()
            record.save()
            DebriefActionRoutingService._sync_debrief_status(record.debrief, status)
        DebriefActionRoutingService._notify(
            record, f"Action update: {record.get_status_display()}", note or record.action
        )
        return record

    @staticmethod
    def escalate(principal, action_id: str, *, note: str) -> DailyDebriefAction:
        return DebriefActionRoutingService.update_status(principal, action_id, status=DebriefActionStatus.ESCALATED, note=note)

    @staticmethod
    def _sync_debrief_status(debrief, new_action_status: str) -> None:
        """Keep the parent debrief's lifecycle in step with its actions (§9):
        any escalated action escalates the debrief; when the last escalation
        clears, the debrief falls back to ACTION_REQUIRED (open work remains)
        or RESOLVED (nothing open). Restricted incidents keep their status —
        the same guard `create()` applies."""
        if debrief.status == DebriefStatus.RESTRICTED_INCIDENT:
            return
        has_escalated = debrief.actions.filter(status=DebriefActionStatus.ESCALATED).exists()
        has_open = debrief.actions.exclude(status__in=TERMINAL_STATUSES).exists()
        target = None
        if has_escalated:
            target = DebriefStatus.ESCALATED
        elif debrief.status == DebriefStatus.ESCALATED:
            target = DebriefStatus.ACTION_REQUIRED if has_open else DebriefStatus.RESOLVED
        elif new_action_status == DebriefActionStatus.RESOLVED and not has_open:
            target = DebriefStatus.RESOLVED
        if target and debrief.status != target:
            debrief.status = target
            debrief.save(update_fields=["status"])

    @staticmethod
    def _notify(record: DailyDebriefAction, title: str, body: str) -> None:
        from apps.notifications.services import WorkflowNotificationService

        recipients = {record.owner_user_id, record.assigned_by_user_id} - {None, ""}
        if not recipients:
            return
        WorkflowNotificationService.trigger(
            event_type="field_debrief_action_update", category="field_debrief",
            priority="high" if record.priority in ("high", "critical") else "normal",
            title=title, body=body, context_type="field_debrief", context_id=record.debrief_id,
            recipients=list(recipients),
        )
