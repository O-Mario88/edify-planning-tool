"""Data Repair Center — controlled correction of inconsistent records.

Admin can *see* every business record and can change none of them through the
ordinary pages (apps/admin_ops/middleware.py enforces that). Real
inconsistencies still have to be fixable, so they are fixed here, through a
flow that leaves evidence:

    detect -> propose -> list affected records -> dry run -> impact preview
    -> apply (idempotent) -> verify -> audit -> close

Two kinds of repair, deliberately separated:

* **Automatic** — provably mechanical and confined to platform state (stale
  notifications, orphaned alert rows). These can be applied.
* **Referred** — anything needing business judgement, such as a scheduled
  activity with no cost line. The platform will not invent a number; the
  repair raises an Admin work item that routes the decision to the role that
  owns it. This is the difference between repairing data and quietly making it
  up.

A repair is idempotent by construction: ``find`` is re-run inside ``apply``, so
running it twice fixes nothing the second time, and a half-finished run resumes
safely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from django.utils import timezone

from apps.admin_ops.models import Severity, WorkItemCategory
from apps.admin_ops.services import AdminWorkItemService, _require_admin
from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest


@dataclass(frozen=True)
class RepairSpec:
    key: str
    title: str
    description: str
    # What a fixed record looks like — shown in the impact preview so the
    # Admin approves an outcome, not a button.
    outcome: str
    find: Callable[[], list]
    apply: Callable[[list], int] | None = None
    referral: str = ""

    @property
    def automatic(self) -> bool:
        return self.apply is not None


# ── Repair 1: notifications outliving their condition ────────────────────────


def _find_stale_incident_notifications() -> list:
    from apps.admin_ops.models import IncidentStatus, SystemIncident
    from apps.notifications.models import Notification

    resolved = set(
        SystemIncident.objects.filter(
            status__in=[IncidentStatus.RESOLVED, IncidentStatus.CLOSED]
        ).values_list("id", flat=True)
    )
    if not resolved:
        return []
    return list(
        Notification.objects.filter(
            source_event_type="admin_ops.incident.detected",
            context_id__in=resolved,
            status="unread",
        )
    )


def _apply_stale_incident_notifications(rows: list) -> int:
    from apps.notifications.models import Notification

    if not rows:
        return 0
    return Notification.objects.filter(id__in=[r.id for r in rows]).update(
        status="archived", read_at=timezone.now(), updated_at=timezone.now()
    )


# ── Repair 2: incidents resolved but never closed ────────────────────────────


def _find_long_resolved_incidents() -> list:
    from datetime import timedelta

    from apps.admin_ops.models import IncidentStatus, SystemIncident

    cutoff = timezone.now() - timedelta(days=30)
    return list(
        SystemIncident.objects.filter(
            status=IncidentStatus.RESOLVED, resolved_at__lt=cutoff
        )
    )


def _apply_long_resolved_incidents(rows: list) -> int:
    from apps.admin_ops.models import IncidentStatus, SystemIncident

    if not rows:
        return 0
    return SystemIncident.objects.filter(id__in=[r.id for r in rows]).update(
        status=IncidentStatus.CLOSED, updated_at=timezone.now()
    )


# ── Repair 3: scheduled work with no cost line (referred, never automatic) ───


def _find_uncosted_scheduled_activities() -> list:
    from apps.activities.models import Activity

    return list(
        Activity.objects.filter(
            deleted_at__isnull=True, status="scheduled", cost_missing=True
        ).select_related("school")[:200]
    )


REPAIRS: dict[str, RepairSpec] = {
    spec.key: spec
    for spec in (
        RepairSpec(
            key="stale_incident_notifications",
            title="Notifications for incidents that are already resolved",
            description=(
                "A notification whose condition no longer holds keeps claiming "
                "the Admin's attention forever."
            ),
            outcome="Each notification is archived; the incident is untouched.",
            find=_find_stale_incident_notifications,
            apply=_apply_stale_incident_notifications,
        ),
        RepairSpec(
            key="long_resolved_incidents",
            title="Incidents resolved over 30 days ago and never closed",
            description=(
                "A resolved incident stays reopenable; after a month without "
                "recurrence it belongs in the closed record."
            ),
            outcome=(
                "Status moves resolved -> closed. A later recurrence still "
                "reopens it, so no history is lost."
            ),
            find=_find_long_resolved_incidents,
            apply=_apply_long_resolved_incidents,
        ),
        RepairSpec(
            key="uncosted_scheduled_activities",
            title="Scheduled activities carrying no cost line",
            description=(
                "The activity will never reach a fund request, so the work is "
                "planned but cannot be funded."
            ),
            outcome=(
                "No automatic change. Each is referred to the role that owns "
                "the costing decision."
            ),
            find=_find_uncosted_scheduled_activities,
            referral=(
                "Costing is a business decision with money attached. The "
                "platform must never invent a figure, so this repair raises an "
                "Admin work item to chase the owning role instead."
            ),
        ),
    )
}


class DataRepairService:
    @staticmethod
    def catalogue(principal) -> list[dict]:
        _require_admin(principal)
        return [
            {
                "key": spec.key,
                "title": spec.title,
                "description": spec.description,
                "outcome": spec.outcome,
                "automatic": spec.automatic,
                "referral": spec.referral,
                "affected": len(spec.find()),
            }
            for spec in REPAIRS.values()
        ]

    @staticmethod
    def dry_run(principal, key: str) -> dict:
        """List the affected records and the outcome — changing nothing."""
        _require_admin(principal)
        spec = REPAIRS.get(key)
        if spec is None:
            raise BadRequest(f"No such repair: {key}")
        rows = spec.find()
        audit_log(
            action="admin_ops.repair.dry_run",
            subject_kind="data_repair",
            subject_id=key,
            actor_id=getattr(principal, "user_id", None),
            actor_role="Admin",
            payload={"affected": len(rows)},
        )
        return {
            "key": key,
            "title": spec.title,
            "outcome": spec.outcome,
            "automatic": spec.automatic,
            "referral": spec.referral,
            "affected": len(rows),
            "records": [str(r) for r in rows[:50]],
            "truncated": len(rows) > 50,
        }

    @staticmethod
    def apply(principal, key: str, reason: str) -> dict:
        _require_admin(principal)
        if not (reason or "").strip():
            raise BadRequest("A repair requires a reason — it is audit evidence.")
        spec = REPAIRS.get(key)
        if spec is None:
            raise BadRequest(f"No such repair: {key}")

        # Re-find inside apply: the preview may be minutes old, and this is
        # what makes a second run a no-op rather than a second change.
        rows = spec.find()

        if not spec.automatic:
            item = AdminWorkItemService.create(
                principal,
                title=f"Refer for correction: {spec.title} ({len(rows)} record(s))",
                category=WorkItemCategory.DATA_REPAIR,
                severity=Severity.MEDIUM,
                description=f"{spec.description}\n\n{spec.referral}",
                scheduled_date=timezone.localdate(),
                next_action="Contact the owning role",
            )
            audit_log(
                action="admin_ops.repair.referred",
                subject_kind="data_repair",
                subject_id=key,
                actor_id=getattr(principal, "user_id", None),
                actor_role="Admin",
                reason=reason,
                payload={"affected": len(rows), "work_item": item.reference},
            )
            return {
                "referred": True,
                "affected": len(rows),
                "work_item": item.reference,
            }

        changed = spec.apply(rows)
        remaining = len(spec.find())  # verification, in the same breath
        audit_log(
            action="admin_ops.repair.applied",
            subject_kind="data_repair",
            subject_id=key,
            actor_id=getattr(principal, "user_id", None),
            actor_role="Admin",
            reason=reason,
            payload={
                "affected": len(rows),
                "changed": changed,
                "remaining_after": remaining,
            },
        )
        return {
            "referred": False,
            "affected": len(rows),
            "changed": changed,
            "verified": remaining == 0,
            "remaining": remaining,
        }
