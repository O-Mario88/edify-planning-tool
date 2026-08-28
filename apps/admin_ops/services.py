"""Canonical services for Admin platform operations.

Every path — page, HTMX, background job, security hook — goes through these.
No view assigns a ticket/incident/work-item status directly: transitions are
validated here, audited through apps.audit, and announced through the existing
notification service (which carries the dedupe/reminder machinery and the
deep-link resolution these workflows require).
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden
from apps.admin_ops.models import (
    AdminOperationsWorkItem,
    IncidentStatus,
    MaintenanceTemplate,
    Severity,
    SupportTicket,
    SystemIncident,
    TicketStatus,
    WorkItemCategory,
    WorkItemStatus,
)


# ── Shared helpers ───────────────────────────────────────────────────────────


def _admin_users():
    from apps.accounts.models import User

    return User.objects.filter(
        active_role="Admin", is_active=True, deleted_at__isnull=True
    )


def _require_admin(principal):
    if getattr(principal, "active_role", None) != "Admin":
        raise Forbidden("Platform operations are Admin-only.")


def _next_reference(prefix: str, model) -> str:
    n = model.objects.count() + 1
    for attempt in range(50):
        candidate = f"{prefix}-{n + attempt:06d}"
        if not model.objects.filter(reference=candidate).exists():
            return candidate
    raise BadRequest("Could not allocate a reference.")


def _notify_admins(
    event_type, category, priority, title, body, context_type, context_id
):
    from apps.notifications.services import WorkflowNotificationService

    return WorkflowNotificationService.trigger(
        event_type=event_type,
        category=category,
        priority=priority,
        title=title,
        body=body,
        context_type=context_type,
        context_id=context_id,
        recipients=_admin_users(),
    )


def push_live(event_type: str, payload: dict | None = None) -> None:
    """Push a platform-operations event to every Admin's open session.

    Deliberately NOT ``domain_events.emit``: that helper audits and creates
    notifications too, and these services already do both -- routing through it
    would double every audit row and every notification. This is the live
    channel only, published after commit so the UI is never told about a change
    that has not landed.
    """
    try:
        from django.db import transaction

        from apps.realtime.bus import bus

        admin_ids = list(_admin_users().values_list("id", flat=True))
        if not admin_ids:
            return
        event = {
            "type": event_type,
            "at": timezone.now().isoformat(),
            "meta": payload or {},
        }
        transaction.on_commit(lambda: bus.publish_many(admin_ids, event))
    except Exception:  # never break the workflow to deliver a live update
        pass


def _resolve_admin_notifications(event_types, context_type, context_id):
    from apps.notifications.services import resolve_condition

    resolve_condition(event_types, context_type, context_id)


# ── Support tickets ──────────────────────────────────────────────────────────

# The lifecycle of §12, as an explicit transition map. A state not listed as a
# source cannot move; a target not listed for a source cannot be reached.
_TICKET_TRANSITIONS: dict[str, set[str]] = {
    TicketStatus.SUBMITTED: {
        TicketStatus.TRIAGED,
        TicketStatus.DUPLICATE,
        TicketStatus.INVALID,
        TicketStatus.CANCELLED,
    },
    TicketStatus.TRIAGED: {
        TicketStatus.MORE_INFO,
        TicketStatus.PLANNED,
        TicketStatus.IN_PROGRESS,
        TicketStatus.DUPLICATE,
        TicketStatus.INVALID,
    },
    TicketStatus.MORE_INFO: {TicketStatus.TRIAGED, TicketStatus.CANCELLED},
    TicketStatus.PLANNED: {TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED},
    TicketStatus.IN_PROGRESS: {
        TicketStatus.WAITING_ON_USER,
        TicketStatus.FIX_READY,
    },
    TicketStatus.WAITING_ON_USER: {TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED},
    TicketStatus.FIX_READY: {TicketStatus.VERIFICATION},
    TicketStatus.VERIFICATION: {TicketStatus.RESOLVED, TicketStatus.IN_PROGRESS},
    TicketStatus.RESOLVED: {TicketStatus.CLOSED, TicketStatus.REOPENED},
    TicketStatus.CLOSED: {TicketStatus.REOPENED},
    TicketStatus.REOPENED: {TicketStatus.TRIAGED},
}

# What context capture must never include (§11).
_FORBIDDEN_CONTEXT_KEYS = {"password", "token", "secret", "authorization", "cookie"}


class SupportTicketService:
    @staticmethod
    def create(reporter, data: dict, context: dict | None = None) -> SupportTicket:
        """Any signed-in user reports a platform problem.

        `context` is the auto-captured support context (route, page, object,
        browser, request id). Sensitive keys are refused outright rather than
        silently dropped, so a caller that tries to capture them fails loudly
        in development instead of leaking quietly in production.
        """
        context = context or {}
        leaked = {k for k in context if k.lower() in _FORBIDDEN_CONTEXT_KEYS}
        if leaked:
            raise BadRequest(f"Support context must never carry: {sorted(leaked)}")

        title = (data.get("title") or "").strip()
        if not title:
            raise BadRequest("A short summary of the problem is required.")

        with transaction.atomic():
            ticket = SupportTicket.objects.create(
                reference=_next_reference("TCK", SupportTicket),
                title=title[:255],
                category=data.get("category") or "other",
                description=(data.get("description") or "").strip(),
                urgency=data.get("urgency") or Severity.MEDIUM,
                reporter_id=getattr(reporter, "user_id", None)
                or getattr(reporter, "id", ""),
                reporter_role=getattr(reporter, "active_role", "") or "",
                route=(context.get("route") or "")[:255],
                page_title=(context.get("page_title") or "")[:255],
                object_type=(context.get("object_type") or "")[:64],
                object_id=(context.get("object_id") or "")[:64],
                browser=(context.get("browser") or "")[:255],
                request_id=(context.get("request_id") or "")[:64],
            )

        audit_log(
            action="admin_ops.ticket.submitted",
            subject_kind="support_ticket",
            subject_id=ticket.id,
            actor_id=ticket.reporter_id,
            actor_role=ticket.reporter_role,
            payload={"reference": ticket.reference, "category": ticket.category},
        )
        push_live(
            "support.ticket.created",
            {"reference": ticket.reference, "category": ticket.category},
        )
        _notify_admins(
            event_type="admin_ops.ticket.created",
            category="support",
            priority="urgent" if ticket.urgency == Severity.CRITICAL else "high",
            title=f"Support ticket {ticket.reference}: {ticket.title}",
            body=f"{ticket.reporter_role or 'A user'} reported "
            f"{ticket.get_category_display()} on {ticket.route or 'an unknown page'}.",
            context_type="support_ticket",
            context_id=ticket.id,
        )
        return ticket

    @staticmethod
    def transition(
        ticket_id: str, to_status: str, principal, note: str = ""
    ) -> SupportTicket:
        _require_admin(principal)
        with transaction.atomic():
            ticket = SupportTicket.objects.select_for_update().get(id=ticket_id)
            allowed = _TICKET_TRANSITIONS.get(ticket.status, set())
            if to_status not in allowed:
                raise BadRequest(
                    f"A ticket in '{ticket.status}' cannot move to '{to_status}'."
                )
            previous = ticket.status
            ticket.status = to_status
            update = ["status", "updated_at"]
            if to_status == TicketStatus.RESOLVED:
                ticket.resolution = note or ticket.resolution
                ticket.resolved_at = timezone.now()
                update += ["resolution", "resolved_at"]
            if to_status == TicketStatus.CLOSED:
                ticket.closed_at = timezone.now()
                update.append("closed_at")
            if not ticket.owner_id:
                ticket.owner_id = getattr(principal, "user_id", None)
                update.append("owner_id")
            ticket.save(update_fields=update)

        audit_log(
            action=f"admin_ops.ticket.{to_status}",
            subject_kind="support_ticket",
            subject_id=ticket.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role="Admin",
            reason=note or None,
            payload={"from": previous, "to": to_status},
        )
        push_live(
            "support.ticket.updated",
            {"reference": ticket.reference, "status": to_status},
        )
        if to_status == TicketStatus.RESOLVED:
            SupportTicketService._notify_reporter(ticket)
        if to_status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
            _resolve_admin_notifications(
                ["admin_ops.ticket.created"], "support_ticket", ticket.id
            )
        return ticket

    @staticmethod
    def _notify_reporter(ticket: SupportTicket) -> None:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type="admin_ops.ticket.resolved",
            category="support",
            priority="normal",
            title=f"Your support ticket {ticket.reference} is resolved",
            body=ticket.resolution or "The reported problem has been fixed.",
            context_type="support_ticket_reporter",
            context_id=ticket.id,
            recipients=[ticket.reporter_id],
        )

    @staticmethod
    def triage(
        ticket_id: str,
        principal,
        *,
        severity: str,
        schedule_for: date | None = None,
    ) -> AdminOperationsWorkItem:
        """Triage creates the work item — critical work skips the backlog.

        A critical ticket lands in Admin My Plan immediately (scheduled today);
        anything else enters the Admin Planning backlog until it is scheduled.
        """
        _require_admin(principal)
        ticket = SupportTicket.objects.get(id=ticket_id)
        SupportTicketService.transition(ticket.id, TicketStatus.TRIAGED, principal)

        if severity == Severity.CRITICAL and schedule_for is None:
            schedule_for = timezone.localdate()

        item = AdminWorkItemService.create(
            principal,
            title=f"[{ticket.reference}] {ticket.title}",
            category=WorkItemCategory.SUPPORT,
            severity=severity,
            description=ticket.description,
            affected_route=ticket.route,
            ticket=ticket,
            scheduled_date=schedule_for,
        )
        SupportTicketService.transition(
            ticket.id,
            TicketStatus.IN_PROGRESS if schedule_for else TicketStatus.PLANNED,
            principal,
        )
        return item


# ── System incidents ─────────────────────────────────────────────────────────

_MAX_SAMPLES = 20


def _default_incident_owner_id() -> str | None:
    """Resolve the configured human owner without making detection fragile."""
    email = str(getattr(settings, "INCIDENT_OWNER_EMAIL", "") or "").strip()
    if not email:
        return None
    from apps.accounts.models import User

    return (
        User.objects.filter(
            email__iexact=email,
            is_active=True,
            deleted_at__isnull=True,
        )
        .values_list("id", flat=True)
        .first()
    )


class SystemIncidentService:
    @staticmethod
    def signature_of(*, environment: str, category: str, route: str, error: str) -> str:
        """The dedupe key: one recurring defect is one incident (§14)."""
        raw = "|".join((environment, category, route, error))
        return hashlib.sha256(raw.encode()).hexdigest()[:40]

    @staticmethod
    def report(
        *,
        title: str,
        category: str,
        severity: str,
        route: str = "",
        component: str = "",
        error: str = "",
        environment: str = "local",
        request_id: str = "",
        detail: dict | None = None,
    ) -> SystemIncident:
        now = timezone.now()
        signature = SystemIncidentService.signature_of(
            environment=environment, category=category, route=route, error=error
        )

        with transaction.atomic():
            incident = (
                SystemIncident.objects.select_for_update()
                .filter(signature=signature)
                .first()
            )
            if incident is None:
                try:
                    incident = SystemIncident.objects.create(
                        reference=_next_reference("INC", SystemIncident),
                        signature=signature,
                        title=title[:255],
                        category=category,
                        severity=severity,
                        affected_route=route[:255],
                        affected_component=component[:128],
                        detail=detail or {},
                        samples=[request_id] if request_id else [],
                        first_detected_at=now,
                        last_detected_at=now,
                        owner_id=_default_incident_owner_id(),
                    )
                    created = True
                except IntegrityError:
                    incident = SystemIncident.objects.select_for_update().get(
                        signature=signature
                    )
                    created = False
            else:
                created = False

            if not created:
                incident.occurrence_count += 1
                incident.last_detected_at = now
                update = ["occurrence_count", "last_detected_at", "updated_at"]
                if request_id and request_id not in incident.samples:
                    incident.samples = (incident.samples + [request_id])[-_MAX_SAMPLES:]
                    update.append("samples")
                # A resolved defect that fires again is the same defect, back.
                if incident.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
                    incident.status = IncidentStatus.OPEN
                    incident.reopened_count += 1
                    incident.resolved_at = None
                    update += ["status", "reopened_count", "resolved_at"]
                    audit_log(
                        action="admin_ops.incident.reopened",
                        subject_kind="system_incident",
                        subject_id=incident.id,
                        payload={"reference": incident.reference},
                    )
                incident.save(update_fields=update)

        if created:
            audit_log(
                action="admin_ops.incident.detected",
                subject_kind="system_incident",
                subject_id=incident.id,
                payload={"reference": incident.reference, "signature": signature},
            )
            if severity == Severity.CRITICAL:
                # Critical incidents bypass the Planning backlog (§10).
                AdminWorkItemService.create(
                    None,
                    title=f"[{incident.reference}] {incident.title}",
                    category=WorkItemCategory.INCIDENT,
                    severity=severity,
                    affected_route=route,
                    incident=incident,
                    scheduled_date=timezone.localdate(),
                    next_action="Acknowledge Incident",
                )
        push_live(
            "incident.detected" if created else "incident.recurred",
            {
                "reference": incident.reference,
                "severity": severity,
                "occurrences": incident.occurrence_count,
            },
        )
        # Created or repeated: the admin notification is refreshed, not
        # duplicated — the notification service updates the existing row and
        # increments its reminder count for the same context.
        _notify_admins(
            event_type="admin_ops.incident.detected",
            category="availability",
            priority="urgent" if severity == Severity.CRITICAL else "high",
            title=f"{incident.reference}: {incident.title}",
            body=(
                f"{incident.get_severity_display()} · {incident.affected_route or component or 'platform'} · "
                f"seen {incident.occurrence_count}×"
            ),
            context_type="system_incident",
            context_id=incident.id,
        )
        return incident

    @staticmethod
    def acknowledge(incident_id: str, principal) -> SystemIncident:
        _require_admin(principal)
        incident = SystemIncident.objects.get(id=incident_id)
        if incident.status != IncidentStatus.OPEN:
            raise BadRequest("Only an open incident can be acknowledged.")
        incident.status = IncidentStatus.ACKNOWLEDGED
        incident.acknowledged_at = timezone.now()
        incident.owner_id = incident.owner_id or getattr(principal, "user_id", None)
        incident.save(
            update_fields=["status", "acknowledged_at", "owner_id", "updated_at"]
        )
        audit_log(
            action="admin_ops.incident.acknowledged",
            subject_kind="system_incident",
            subject_id=incident.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role="Admin",
        )
        return incident

    @staticmethod
    def resolve(incident_id: str, principal, note: str = "") -> SystemIncident:
        _require_admin(principal)
        incident = SystemIncident.objects.get(id=incident_id)
        if incident.status not in (
            IncidentStatus.ACKNOWLEDGED,
            IncidentStatus.MITIGATED,
        ):
            raise BadRequest("Acknowledge an incident before resolving it.")
        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = timezone.now()
        incident.save(update_fields=["status", "resolved_at", "updated_at"])
        audit_log(
            action="admin_ops.incident.resolved",
            subject_kind="system_incident",
            subject_id=incident.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role="Admin",
            reason=note or None,
        )
        push_live("incident.resolved", {"reference": incident.reference})
        _resolve_admin_notifications(
            ["admin_ops.incident.detected"], "system_incident", incident.id
        )
        return incident


# ── Admin work items: Planning backlog ⇄ Admin My Plan ───────────────────────


class AdminWorkItemService:
    @staticmethod
    def create(
        principal,
        *,
        title: str,
        category: str,
        severity: str = Severity.MEDIUM,
        description: str = "",
        affected_module: str = "",
        affected_route: str = "",
        due_date: date | None = None,
        scheduled_date: date | None = None,
        next_action: str = "",
        ticket: SupportTicket | None = None,
        incident: SystemIncident | None = None,
    ) -> AdminOperationsWorkItem:
        if principal is not None:
            _require_admin(principal)
        item = AdminOperationsWorkItem.objects.create(
            reference=_next_reference("OPS", AdminOperationsWorkItem),
            title=title[:255],
            category=category,
            severity=severity,
            description=description,
            affected_module=affected_module[:128],
            affected_route=affected_route[:255],
            due_date=due_date,
            scheduled_date=scheduled_date,
            status=WorkItemStatus.SCHEDULED
            if scheduled_date
            else WorkItemStatus.BACKLOG,
            next_action=next_action
            or ("Start Investigation" if incident else "Triage"),
            owner_id=getattr(principal, "user_id", None) if principal else None,
            ticket=ticket,
            incident=incident,
        )
        audit_log(
            action="admin_ops.work_item.created",
            subject_kind="admin_work_item",
            subject_id=item.id,
            actor_id=getattr(principal, "user_id", None) if principal else None,
            actor_role="Admin" if principal else "system",
            payload={
                "reference": item.reference,
                "category": category,
                "scheduled": bool(scheduled_date),
            },
        )
        return item

    @staticmethod
    def schedule(item_id: str, principal, when: date) -> AdminOperationsWorkItem:
        """Scheduling is the Planning → My Plan handoff."""
        _require_admin(principal)
        item = AdminOperationsWorkItem.objects.get(id=item_id)
        if item.status not in (WorkItemStatus.BACKLOG, WorkItemStatus.SCHEDULED):
            raise BadRequest(f"A {item.status} work item cannot be (re)scheduled.")
        item.scheduled_date = when
        item.status = WorkItemStatus.SCHEDULED
        item.owner_id = item.owner_id or getattr(principal, "user_id", None)
        item.save(update_fields=["scheduled_date", "status", "owner_id", "updated_at"])
        push_live(
            "admin_work.scheduled",
            {"reference": item.reference, "date": when.isoformat()},
        )
        audit_log(
            action="admin_ops.work_item.scheduled",
            subject_kind="admin_work_item",
            subject_id=item.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role="Admin",
            payload={"scheduled_date": when.isoformat()},
        )
        return item

    @staticmethod
    def start(item_id: str, principal) -> AdminOperationsWorkItem:
        _require_admin(principal)
        item = AdminOperationsWorkItem.objects.get(id=item_id)
        if item.status != WorkItemStatus.SCHEDULED:
            raise BadRequest("Only scheduled work can be started.")
        item.status = WorkItemStatus.IN_PROGRESS
        item.next_action = "Complete and verify"
        item.save(update_fields=["status", "next_action", "updated_at"])
        audit_log(
            action="admin_ops.work_item.started",
            subject_kind="admin_work_item",
            subject_id=item.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role="Admin",
        )
        return item

    @staticmethod
    def complete(
        item_id: str, principal, verification_note: str
    ) -> AdminOperationsWorkItem:
        """No Admin task disappears without verification: completion requires
        a note saying how the result was checked."""
        _require_admin(principal)
        if not (verification_note or "").strip():
            raise BadRequest("Completion requires a verification note.")
        item = AdminOperationsWorkItem.objects.get(id=item_id)
        if item.status not in (WorkItemStatus.IN_PROGRESS, WorkItemStatus.MONITORING):
            raise BadRequest("Only in-progress or monitoring work can be completed.")
        item.status = WorkItemStatus.DONE
        item.verification_note = verification_note.strip()
        item.completed_at = timezone.now()
        item.next_action = ""
        item.save(
            update_fields=[
                "status",
                "verification_note",
                "completed_at",
                "next_action",
                "updated_at",
            ]
        )
        push_live("admin_work.completed", {"reference": item.reference})
        audit_log(
            action="admin_ops.work_item.completed",
            subject_kind="admin_work_item",
            subject_id=item.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role="Admin",
            reason=verification_note.strip()[:255],
        )
        return item


class AdminPlanningService:
    """The unscheduled platform backlog (§8)."""

    @staticmethod
    def context(principal) -> dict:
        _require_admin(principal)
        backlog = list(
            AdminOperationsWorkItem.objects.filter(
                status=WorkItemStatus.BACKLOG
            ).order_by("severity", "-created_at")
        )
        severity_rank = {
            s: i
            for i, s in enumerate(
                [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]
            )
        }
        backlog.sort(key=lambda i: (severity_rank.get(i.severity, 9), i.created_at))
        open_incidents = SystemIncident.objects.exclude(
            status__in=[IncidentStatus.RESOLVED, IncidentStatus.CLOSED]
        ).order_by("-last_detected_at")
        untriaged = SupportTicket.objects.filter(
            status=TicketStatus.SUBMITTED
        ).order_by("-created_at")
        return {
            "backlog": backlog,
            "open_incidents": list(open_incidents[:50]),
            "untriaged_tickets": list(untriaged[:50]),
        }


class AdminMyPlanService:
    """The Admin's scheduled operating list (§9), sectioned by urgency."""

    @staticmethod
    def context(principal) -> dict:
        _require_admin(principal)
        today = timezone.localdate()
        week_end = today + timedelta(days=6 - today.weekday())
        active = AdminOperationsWorkItem.objects.filter(
            status__in=[
                WorkItemStatus.SCHEDULED,
                WorkItemStatus.IN_PROGRESS,
                WorkItemStatus.WAITING,
                WorkItemStatus.MONITORING,
            ]
        ).order_by("scheduled_date", "-created_at")

        sections = {
            "critical_now": [],
            "due_today": [],
            "needs_attention": [],
            "planned_this_week": [],
            "planned_later": [],
            "monitoring": [],
        }
        for item in active:
            if item.status == WorkItemStatus.MONITORING:
                sections["monitoring"].append(item)
            elif (
                item.severity == Severity.CRITICAL
                and item.status != WorkItemStatus.DONE
            ):
                sections["critical_now"].append(item)
            elif item.due_date and item.due_date < today:
                sections["needs_attention"].append(item)
            elif item.scheduled_date == today:
                sections["due_today"].append(item)
            elif item.scheduled_date and item.scheduled_date <= week_end:
                sections["planned_this_week"].append(item)
            else:
                sections["planned_later"].append(item)

        recently_done = AdminOperationsWorkItem.objects.filter(
            status=WorkItemStatus.DONE
        ).order_by("-completed_at")[:8]
        return {"sections": sections, "recently_done": list(recently_done)}


class MaintenanceService:
    @staticmethod
    def generate_due(today: date | None = None) -> int:
        """Materialise scheduled work items for every due template.

        Idempotent per due date: the template's ``next_due_date`` only advances
        after its item is created, so a crashed run resumes; a completed run
        will not double-create.
        """
        today = today or timezone.localdate()
        generated = 0
        for template in MaintenanceTemplate.objects.filter(
            active=True, next_due_date__lte=today
        ):
            AdminWorkItemService.create(
                None,
                title=template.name,
                category=template.category,
                severity=Severity.MEDIUM,
                description=template.description,
                scheduled_date=template.next_due_date,
                due_date=template.next_due_date,
                next_action="Begin Maintenance",
            )
            template.next_due_date = template.next_due_date + timedelta(
                days=template.frequency_days
            )
            template.save(update_fields=["next_due_date", "updated_at"])
            generated += 1
        return generated


# ── Security: failed-login threshold (§17) ───────────────────────────────────

FAILED_LOGIN_ALERT_THRESHOLD = 5


class SecurityAlertService:
    @staticmethod
    def failed_login_threshold_reached(
        *, user_id: str, masked_identifier: str, streak: int, locked: bool
    ) -> SystemIncident:
        """Five consecutive failures → one security incident + admin alert.

        Deliberately carries no password material of any kind, and the caller
        (the lockout service) never passes any. The public login response is
        untouched — this only observes.
        """
        return SystemIncidentService.report(
            title=f"Failed-login threshold reached for {masked_identifier}",
            category=WorkItemCategory.SECURITY,
            severity=Severity.HIGH,
            route="/login",
            component="authentication",
            error=f"failed_login_threshold:{user_id}",
            detail={
                "masked_identifier": masked_identifier,
                "streak": streak,
                "locked": locked,
            },
        )

    @staticmethod
    def mask(email: str) -> str:
        name, _, domain = (email or "").partition("@")
        if not domain:
            return "unknown"
        keep = name[:2]
        return f"{keep}{'*' * max(1, len(name) - 2)}@{domain}"


# ── Admin dashboard: the Platform Operations command centre (§21) ────────────


class AdminOpsDashboardService:
    """The eight decision metrics an Admin opens the platform to answer.

    Every one is a platform-operations question with an owner and a next step.
    Country programme performance deliberately has no place here: it is not
    Admin's remit, and putting it on this page was what made Admin look like a
    business role in the first place.
    """

    @staticmethod
    def summary(principal) -> dict:
        _require_admin(principal)
        today = timezone.localdate()
        open_incidents = SystemIncident.objects.exclude(
            status__in=[IncidentStatus.RESOLVED, IncidentStatus.CLOSED]
        )
        active_items = AdminOperationsWorkItem.objects.filter(
            status__in=[
                WorkItemStatus.BACKLOG,
                WorkItemStatus.SCHEDULED,
                WorkItemStatus.IN_PROGRESS,
                WorkItemStatus.WAITING,
                WorkItemStatus.MONITORING,
            ]
        )
        closed_ticket_states = [
            TicketStatus.CLOSED,
            TicketStatus.RESOLVED,
            TicketStatus.INVALID,
            TicketStatus.CANCELLED,
            TicketStatus.DUPLICATE,
        ]
        return {
            "critical_incidents": open_incidents.filter(
                severity=Severity.CRITICAL
            ).count(),
            "unacknowledged_incidents": open_incidents.filter(
                status=IncidentStatus.OPEN
            ).count(),
            "open_tickets": SupportTicket.objects.exclude(
                status__in=closed_ticket_states
            ).count(),
            "untriaged_tickets": SupportTicket.objects.filter(
                status=TicketStatus.SUBMITTED
            ).count(),
            "overdue_admin_work": active_items.filter(due_date__lt=today).count(),
            "unscheduled_work": active_items.filter(
                status=WorkItemStatus.BACKLOG
            ).count(),
            "security_alerts": open_incidents.filter(
                category=WorkItemCategory.SECURITY
            ).count(),
            "job_incidents": open_incidents.filter(
                category=WorkItemCategory.JOB_FAILURE
            ).count(),
            "performance_incidents": open_incidents.filter(
                category=WorkItemCategory.PERFORMANCE
            ).count(),
            "maintenance_due": MaintenanceTemplate.objects.filter(
                active=True, next_due_date__lte=today
            ).count(),
            "critical_now": list(
                active_items.filter(severity=Severity.CRITICAL).order_by(
                    "scheduled_date"
                )[:5]
            ),
            "recent_incidents": list(open_incidents.order_by("-last_detected_at")[:5]),
        }
