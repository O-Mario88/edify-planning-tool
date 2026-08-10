"""§32 — the invariants the corrected scheduling rule depends on.

These are deliberately separate from ``catalogue_health``: that module asks
whether the governed catalogue is internally consistent, while this one asks
whether SCHEDULING still works — whether ordinary support has a path, whether
participant quantities match the activities that carry them, and whether
certified-agency bookings reached the people who have to act on them.

Each check is written so that the healthy answer is zero. Where a check
counts activities rather than configuration, it looks only at live records:
a cancelled booking that no longer appears in a partner's My Plan is the
system working, not a fault.
"""

from django.db.models import Count, F, Q
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.enums import ExecutorType, ParticipantMode

from .models import ActivityCatalogueItem, CatalogueStatus


#: Activity statuses that still represent live, actionable work. A cancelled
#: or rejected record is history and must not be reported as a live fault.
LIVE_STATUSES = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "in_progress",
    "completion_started",
)

#: The standard support every planning context must be able to schedule. If
#: any of these has no active costed catalogue item, ordinary work is blocked
#: again — which is the entire defect this module exists to catch early.
REQUIRED_STANDARD_KINDS = (
    "school_visit",
    "in_school_training",
    "cluster_meeting",
    "cluster_training",
)


def _standard_kind_gaps() -> list[str]:
    covered = set(
        ActivityCatalogueItem.objects.filter(
            status=CatalogueStatus.ACTIVE, standard_support=True
        ).values_list("workflow_kind", flat=True)
    )
    return sorted(set(REQUIRED_STANDARD_KINDS) - covered)


def _duplicate_standard_kinds() -> list[str]:
    """Two standard items for one kind puts the purpose → costing resolver
    back where it started: unable to choose, so it chooses nothing."""
    rows = (
        ActivityCatalogueItem.objects.filter(
            status=CatalogueStatus.ACTIVE, standard_support=True
        )
        .values("workflow_kind")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    return sorted(row["workflow_kind"] for row in rows)


def scheduling_health() -> dict:
    live = Activity.objects.filter(deleted_at__isnull=True, status__in=LIVE_STATUSES)

    standard_gaps = _standard_kind_gaps()
    duplicate_standard = _duplicate_standard_kinds()

    # A Workflow Profile that requires a Project, on an activity that has
    # none. The inverse of the original defect and just as wrong.
    project_required_missing = live.filter(
        catalogue_item__requires_project=True, project_id__isnull=True
    )

    # SSA-guided support that recorded no target intervention has nothing for
    # intervention analytics to attribute it to.
    ssa_guided_without_target = live.filter(
        catalogue_item__requires_current_ssa=True,
        school__isnull=False,
    ).filter(Q(focus_intervention__isnull=True) | Q(focus_intervention=""))

    # A visit carrying a participant quantity. Either a stale drawer value was
    # stored, or a client sent one — and participant counts multiply into
    # cost, so this is a money question, not a tidiness one.
    visit_with_participants = live.filter(
        catalogue_item__participant_mode=ParticipantMode.NONE
    ).filter(
        Q(expected_participants__isnull=False)
        | Q(participants_per_school__isnull=False)
        | Q(teachers_attended__isnull=False)
        | Q(leaders_attended__isnull=False)
    )

    training_without_participants = live.filter(
        catalogue_item__participant_mode__in=[
            ParticipantMode.DIRECT_TOTAL,
            ParticipantMode.BY_CATEGORY,
        ],
    ).filter(Q(expected_participants__isnull=True) | Q(expected_participants=0))

    # The stored total must equal per-school × schools INVITED. Rows created
    # before schools_invited existed are read against the membership
    # snapshot, which is what "the whole cluster" meant for them.
    per_school_live = live.filter(
        catalogue_item__participant_mode=ParticipantMode.PER_SCHOOL,
        participants_per_school__isnull=False,
    )
    cluster_total_mismatch = per_school_live.filter(
        schools_invited__isnull=False
    ).exclude(
        expected_participants=F("participants_per_school") * F("schools_invited")
    ) | per_school_live.filter(
        schools_invited__isnull=True, cluster_school_count_snapshot__isnull=False
    ).exclude(
        expected_participants=F("participants_per_school")
        * F("cluster_school_count_snapshot")
    )

    # More schools invited than the cluster had when it was priced. Every one
    # of them is catered and budgeted for.
    over_invited = live.filter(
        schools_invited__isnull=False,
        cluster_school_count_snapshot__isnull=False,
        schools_invited__gt=F("cluster_school_count_snapshot"),
    )

    agency = live.filter(executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY)
    agency_without_partner = agency.filter(
        Q(assigned_partner_id__isnull=True) | Q(assigned_partner_id="")
    )
    agency_not_certified = agency.exclude(
        assigned_partner_id__in=_certified_partner_ids()
    ).exclude(Q(assigned_partner_id__isnull=True) | Q(assigned_partner_id=""))
    # A booking Edify made that still shows the agency a Schedule action.
    agency_awaiting_partner_schedule = agency.filter(status="assigned_to_partner")
    # My Plan scopes a partner's work by assigned_partner_id and a staff
    # member's by responsible_staff_id. A booking carrying BOTH appears as
    # executable work in two people's plans for one delivery (§24).
    agency_duplicated_in_staff_plan = agency.filter(
        responsible_staff_id__isnull=False
    ).exclude(responsible_staff_id="")
    agency_without_budget_lines = (
        agency.filter(scheduled_date__isnull=False)
        .annotate(lines=Count("schedule_cost_lines"))
        .filter(lines=0)
    )
    # Partner-delivered work must carry the partner delivery type, or partner
    # payment, oversight and My Plan scoping all miss it.
    executor_delivery_mismatch = live.filter(
        executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY
    ).exclude(delivery_type="partner")

    checks = [
        {
            "key": "scheduling_standard_support_available",
            "label": "Standard support with no schedulable Catalogue item",
            "status": "pass" if not standard_gaps else "fail",
            "count": len(standard_gaps),
            "detail": ", ".join(standard_gaps),
        },
        {
            "key": "scheduling_standard_support_ambiguous",
            "label": "More than one standard item costing the same activity type",
            "status": "pass" if not duplicate_standard else "fail",
            "count": len(duplicate_standard),
            "detail": ", ".join(duplicate_standard),
        },
        {
            "key": "scheduling_project_required_missing",
            "label": "Project-required Activity scheduled without a Project",
            "status": "pass" if not project_required_missing.exists() else "fail",
            "count": project_required_missing.count(),
        },
        {
            "key": "scheduling_ssa_guided_without_target",
            "label": "SSA-guided support with no target intervention",
            "status": "pass" if not ssa_guided_without_target.exists() else "warn",
            "count": ssa_guided_without_target.count(),
        },
        {
            "key": "scheduling_visit_participant_values",
            "label": "Visit carrying participant values",
            "status": "pass" if not visit_with_participants.exists() else "fail",
            "count": visit_with_participants.count(),
        },
        {
            "key": "scheduling_training_missing_participants",
            "label": "Training with no planned participants",
            "status": "pass" if not training_without_participants.exists() else "warn",
            "count": training_without_participants.count(),
        },
        {
            "key": "scheduling_cluster_participant_mismatch",
            "label": "Cluster total does not equal per-school × schools invited",
            "status": "pass" if not cluster_total_mismatch.exists() else "fail",
            "count": cluster_total_mismatch.count(),
        },
        {
            "key": "scheduling_cluster_over_invited",
            "label": "More schools invited than the cluster holds",
            "status": "pass" if not over_invited.exists() else "fail",
            "count": over_invited.count(),
        },
        {
            "key": "scheduling_agency_booking_without_agency",
            "label": "Certified agency booking with no agency selected",
            "status": "pass" if not agency_without_partner.exists() else "fail",
            "count": agency_without_partner.count(),
        },
        {
            "key": "scheduling_agency_not_certified",
            "label": "Agency booking held by a partner that is not certified",
            "status": "pass" if not agency_not_certified.exists() else "fail",
            "count": agency_not_certified.count(),
        },
        {
            "key": "scheduling_agency_awaiting_schedule",
            "label": "Booked agency still being asked to schedule",
            "status": (
                "pass" if not agency_awaiting_partner_schedule.exists() else "fail"
            ),
            "count": agency_awaiting_partner_schedule.count(),
        },
        {
            "key": "scheduling_agency_duplicated_in_staff_plan",
            "label": "Agency delivery also executable work in a staff My Plan",
            "status": (
                "pass" if not agency_duplicated_in_staff_plan.exists() else "fail"
            ),
            "count": agency_duplicated_in_staff_plan.count(),
        },
        {
            "key": "scheduling_agency_missing_budget_lines",
            "label": "Scheduled agency booking with no ActivityBudgetLines",
            "status": "pass" if not agency_without_budget_lines.exists() else "fail",
            "count": agency_without_budget_lines.count(),
        },
        {
            "key": "scheduling_executor_delivery_mismatch",
            "label": "Agency executor not carrying Partner delivery type",
            "status": "pass" if not executor_delivery_mismatch.exists() else "fail",
            "count": executor_delivery_mismatch.count(),
        },
    ]

    detected_at = timezone.now().isoformat()
    for check in checks:
        failing = check["status"] != "pass"
        check.update(
            {
                "severity": (
                    "critical"
                    if check["status"] == "fail"
                    else "warning"
                    if check["status"] == "warn"
                    else "none"
                ),
                "expected": "0 unresolved issues",
                "actual": check["count"],
                "owner": (
                    "Country Director / Planning Administrator" if failing else None
                ),
                "directCorrectionAction": (
                    "/settings/activity-catalogue/" if failing else None
                ),
                "detectedAt": detected_at,
                "resolutionStatus": "open" if failing else "resolved",
                "auditHistory": "Audit Log",
            }
        )
    return {
        "healthy": all(check["status"] != "fail" for check in checks),
        "checks": checks,
    }


def _certified_partner_ids():
    from apps.partners.models import Partner

    return Partner.objects.filter(
        deleted_at__isnull=True, is_certified=True
    ).values_list("id", flat=True)


__all__ = ["LIVE_STATUSES", "REQUIRED_STANDARD_KINDS", "scheduling_health"]
