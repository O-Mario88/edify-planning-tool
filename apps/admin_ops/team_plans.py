"""Team Plans — Admin's consolidated, read-only view of everyone's My Plan.

Its purpose is diagnostic: is My Plan being generated, routed and updated
correctly across the platform? So it must show exactly what the users
themselves see, and it must not become a second copy of the data.

Two rules follow, and both are pinned by tests:

1. **Same source.** Rows come from the same ``Activity`` queryset the canonical
   My Plan feed uses (``apps.my_plan.services.get``) — same FY filter, same
   terminal-status exclusion. Nothing is denormalised into an admin table.
2. **Same derivation.** Status label and next action come from the canonical
   ``get_activity_status_label_and_class`` and ``compute_next_action``, not
   from a second interpretation of the status field. If the user's page says
   "Awaiting IA", Team Plans says "Awaiting IA".

Read-only is not a UI convention here: this module exposes no mutation at all,
and the ``RolePermissionService`` boundary refuses Admin the underlying
transitions even if a request reaches them directly.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import Forbidden
from apps.core.fy import get_operational_fy

# The canonical My Plan derivations — imported, never re-implemented.
from apps.my_plan.services import (
    compute_next_action,
    get_activity_status_label_and_class,
)

# Terminal statuses the canonical feed excludes from an active plan.
_TERMINAL = ["closed", "cancelled", "rejected"]

PAGE_SIZE = 100

GROUP_BY_CHOICES = [
    ("user", "User"),
    ("role", "Role"),
    ("activity_type", "Activity Type"),
    ("status", "Workflow State"),
    ("date", "Planned Date"),
]


def _require_admin(principal):
    if getattr(principal, "active_role", None) != "Admin":
        raise Forbidden("Team Plans is an Admin observability surface.")


def _base_queryset(fy: str):
    """The canonical active-plan queryset, unscoped.

    Mirrors ``my_plan.services.get`` exactly except for the per-user scope
    filter — which is the whole point of a consolidated view.
    """
    from apps.activities.models import Activity

    return Activity.objects.filter(deleted_at__isnull=True, fy=fy).exclude(
        status__in=_TERMINAL
    )


def _people_index():
    """staff-profile id and user id → {name, role} for row labelling.

    Activities address their owner by StaffProfile CUID *or* User CUID (see
    ``activities.services.create``), so both spaces are indexed — otherwise
    every row created through the fallback path would show a blank owner.
    """
    from apps.accounts.models import StaffProfile

    index: dict[str, dict] = {}
    for sp in StaffProfile.objects.select_related("user").filter(
        deleted_at__isnull=True
    ):
        entry = {
            "name": getattr(sp.user, "name", "") or sp.id,
            "role": getattr(sp.user, "active_role", "") or "",
            "user_id": sp.user_id,
            "staff_id": sp.id,
        }
        index[sp.id] = entry
        if sp.user_id:
            index[sp.user_id] = entry
    return index


def _partner_index():
    from apps.partners.models import Partner

    return {p.id: p.name for p in Partner.objects.all()}


def _supervised_ids(pl_staff_id: str) -> set[str]:
    """Both identifier spaces for a Program Lead's supervisees."""
    from apps.accounts.models import StaffSupervisorAssignment

    ids: set[str] = set()
    for a in StaffSupervisorAssignment.objects.filter(
        supervisor_id=pl_staff_id
    ).select_related("supervisee"):
        ids.add(a.supervisee_id)
        if a.supervisee and a.supervisee.user_id:
            ids.add(a.supervisee.user_id)
    return ids


def _finance_state(activity) -> str:
    """One honest label for where this activity's money stands."""
    payment = (activity.payment_status or "").strip()
    if not payment or payment == "none":
        return (
            "No payment expected"
            if activity.delivery_type != "partner"
            else "Not started"
        )
    return payment.replace("_", " ").title()


class AdminTeamPlansService:
    @staticmethod
    def get(principal, query: dict | None = None) -> dict:
        _require_admin(principal)
        query = query or {}
        today = timezone.localdate()
        fy = query.get("fy") or get_operational_fy()

        qs = _base_queryset(fy)

        # ── Filters ──────────────────────────────────────────────────────────
        month = (query.get("month") or "").strip()
        if month:
            qs = qs.filter(planned_month=month)
        week = (query.get("week") or "").strip()
        if week:
            qs = qs.filter(planned_week=int(week))
        activity_type = (query.get("activity_type") or "").strip()
        if activity_type:
            qs = qs.filter(activity_type=activity_type)
        status = (query.get("status") or "").strip()
        if status:
            qs = qs.filter(status=status)
        district = (query.get("district") or "").strip()
        if district:
            qs = qs.filter(school__district_id=district)
        project = (query.get("project") or "").strip()
        if project:
            qs = qs.filter(project_id=project)
        partner = (query.get("partner") or "").strip()
        if partner:
            qs = qs.filter(assigned_partner_id=partner)

        user_filter = (query.get("user") or "").strip()
        if user_filter:
            qs = qs.filter(
                Q(responsible_staff_id=user_filter)
                | Q(monitored_by_staff_id=user_filter)
            )

        team = (query.get("team") or "").strip()  # a Program Lead's staff id
        if team:
            supervised = _supervised_ids(team) | {team}
            qs = qs.filter(responsible_staff_id__in=supervised)

        overdue_only = (query.get("overdue") or "").strip() in ("1", "true", "yes")

        people = _people_index()
        partners = _partner_index()

        role_filter = (query.get("role") or "").strip()

        rows = []
        # `Activity.project_id` is a plain CharField, not a relation -- there
        # is no `project` to select_related, and the id is shown as-is.
        for a in qs.select_related("school", "school__district", "cluster").order_by(
            "planned_date", "planned_month", "planned_week"
        )[: PAGE_SIZE * 5]:
            label, status_class = get_activity_status_label_and_class(a, today)
            next_action = compute_next_action(a, today)

            owner = people.get(a.responsible_staff_id or "", {})
            monitor = people.get(a.monitored_by_staff_id or "", {})
            executor = (
                partners.get(a.assigned_partner_id, "Partner")
                if a.delivery_type == "partner"
                else owner.get("name", "Unassigned")
            )
            owner_role = owner.get("role", "")

            if role_filter and owner_role != role_filter:
                continue
            is_overdue = bool(
                a.planned_date and a.planned_date < today and status_class != "done"
            )
            if overdue_only and not is_overdue:
                continue

            rows.append(
                {
                    "id": a.id,
                    "user": owner.get("name") or a.responsible_staff_id or "—",
                    "userId": a.responsible_staff_id or "",
                    "role": owner_role or "—",
                    "activity": a.get_activity_type_display()
                    if hasattr(a, "get_activity_type_display")
                    else a.activity_type,
                    "activityType": a.activity_type,
                    "target": (
                        a.school.name
                        if a.school
                        else (a.cluster.name if a.cluster else None)
                    )
                    or (a.project_id or "—"),
                    "plannedDate": a.planned_date,
                    "status": label,
                    "statusClass": status_class,
                    "rawStatus": a.status,
                    "nextAction": next_action.get("label") or "—",
                    "executor": executor,
                    "managingStaff": monitor.get("name") or "—",
                    "budgetState": "Costed" if not a.cost_missing else "Cost missing",
                    "evidenceState": (a.evidence_status or "none")
                    .replace("_", " ")
                    .title(),
                    "iaState": (
                        getattr(a, "ia_verification_status", "") or "not required"
                    )
                    .replace("_", " ")
                    .title(),
                    "financeState": _finance_state(a),
                    "lastUpdated": a.updated_at,
                    "overdue": is_overdue,
                    "detailUrl": f"/my-plan/{a.id}?support=1",
                    "auditUrl": f"/admin/audit?subject_id={a.id}",
                }
            )

        return {
            "fy": fy,
            "rows": rows[:PAGE_SIZE],
            "total": len(rows),
            "truncated": len(rows) > PAGE_SIZE,
            "filters": query,
            "read_only": True,
            "group_by_choices": GROUP_BY_CHOICES,
            "health": AdminTeamPlansService.health_summary(rows),
        }

    @staticmethod
    def health_summary(rows: list[dict]) -> dict:
        """The Team Plan health preview (§22) — diagnostics, not programme KPIs.

        Every figure names a specific platform defect an Admin can act on, and
        each is computed from the rows already loaded, so the preview costs no
        extra queries.
        """
        no_next_action = sum(1 for r in rows if r["nextAction"] in ("—", "", None))
        overdue = sum(1 for r in rows if r["overdue"])
        cost_missing = sum(1 for r in rows if r["budgetState"] == "Cost missing")
        unassigned = sum(1 for r in rows if not r["userId"])
        return {
            "total_active": len(rows),
            "no_next_action": no_next_action,
            "overdue": overdue,
            "cost_missing": cost_missing,
            "unassigned": unassigned,
        }

    @staticmethod
    def filter_options(fy: str | None = None) -> dict:
        from apps.accounts.models import StaffProfile
        from apps.geography.models import District

        fy = fy or get_operational_fy()
        qs = _base_queryset(fy)
        return {
            "activity_types": sorted(
                {t for t in qs.values_list("activity_type", flat=True) if t}
            ),
            "statuses": sorted({s for s in qs.values_list("status", flat=True) if s}),
            "roles": sorted(
                {
                    r
                    for r in StaffProfile.objects.filter(deleted_at__isnull=True)
                    .select_related("user")
                    .values_list("user__active_role", flat=True)
                    if r
                }
            ),
            "districts": list(District.objects.values("id", "name").order_by("name")),
        }
