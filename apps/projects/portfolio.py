"""The Project Coordinator's school portfolio (owner brief, 2026-09-15).

When a school is added to a project it enters the coordinator's project
portfolio: who added it, when, why it was eligible, the baseline it will be
measured from, and — derived from the canonical records, never stored — where
its planning, visits, training and partner handover have reached.

Adding a school changes nothing about the school itself: its staff owner, its
district and its cluster are untouched, and the coordinator gains no authority
over it outside the project.
"""

from __future__ import annotations

from django.db.models import Q

from apps.schools.school_status import cluster_training_coverage, visit_statuses

#: Project work that still has to happen.
OPEN_PROJECT_ACTIVITY_STATUSES = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "returned",
    "returned_by_pl",
    "returned_by_ia",
    "rescheduled",
)


def portfolio_rows(project, *, fy: str | None = None) -> list[dict]:
    """One row per enrolled school, in the shape the brief lists."""
    from apps.accounts.models import StaffProfile, User
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy
    from apps.partners.models import PartnerAssignment
    from apps.projects.models import ProjectSchoolAssignment

    fy = fy or get_operational_fy()
    assignments = list(
        ProjectSchoolAssignment.objects.filter(project=project)
        .select_related("school", "school__district", "school__region", "baseline_ssa")
        .order_by("school__name")
    )
    if not assignments:
        return []
    schools = [a.school for a in assignments]
    school_ids = [s.id for s in schools]
    visits = visit_statuses(school_ids, fy=fy)
    training = cluster_training_coverage(schools, fy=fy)

    planned: dict[str, int] = {}
    delivered: dict[str, int] = {}
    for row in (
        Activity.objects.filter(
            project_id=project.id, school_id__in=school_ids, deleted_at__isnull=True
        )
        .exclude(status__in=("cancelled", "rejected", "not_planned", "deferred"))
        .values("school_id", "status")
    ):
        planned[row["school_id"]] = planned.get(row["school_id"], 0) + 1
        if row["status"] in (
            "ia_verified",
            "accountant_confirmed",
            "completed",
            "closed",
        ):
            delivered[row["school_id"]] = delivered.get(row["school_id"], 0) + 1

    partner_rows: dict[str, str] = {}
    for assignment in (
        PartnerAssignment.objects.filter(
            project_id=project.id, school_id__in=school_ids
        )
        .select_related("partner")
        .order_by("-created_at")
    ):
        partner_rows.setdefault(
            assignment.school_id,
            f"{assignment.partner.name} · {assignment.status.replace('_', ' ').title()}",
        )

    adder_ids = {a.assigned_by for a in assignments if a.assigned_by}
    names: dict[str, str] = {}
    if adder_ids:
        names.update(
            dict(User.objects.filter(id__in=adder_ids).values_list("id", "name"))
        )
        names.update(
            {
                profile_id: name
                for profile_id, name in StaffProfile.objects.filter(
                    id__in=adder_ids
                ).values_list("id", "user__name")
                if name
            }
        )
    owners = dict(
        StaffProfile.objects.filter(
            Q(id__in=[s.account_owner_id for s in schools if s.account_owner_id])
            | Q(user_id__in=[s.account_owner_id for s in schools if s.account_owner_id])
        ).values_list("id", "user__name")
    )

    rows = []
    for assignment in assignments:
        school = assignment.school
        count = planned.get(school.id, 0)
        rows.append(
            {
                "assignment_id": assignment.id,
                "school_id": school.id,
                "school_code": school.school_id,
                "school_name": school.name,
                "school_url": f"/schools/{school.school_id}",
                "geography": " · ".join(
                    part
                    for part in (
                        school.region.name if school.region_id else "",
                        school.district.name if school.district_id else "",
                    )
                    if part
                ),
                "school_owner": owners.get(school.account_owner_id)
                or school.account_owner_name_raw
                or "Unassigned",
                "added_by": names.get(assignment.assigned_by, "—"),
                "date_added": assignment.created_at,
                "eligibility_reason": assignment.matched_intervention
                or assignment.assignment_reason
                or "Recorded without an SSA match",
                "baseline_score": assignment.baseline_score,
                "baseline_band": assignment.baseline_band,
                "planning_status": (
                    f"{count} planned · {delivered.get(school.id, 0)} delivered"
                    if count
                    else "No project activity planned"
                ),
                "needs_planning": count == 0,
                "visit_status": visits[school.id].label,
                "visit_status_tone": visits[school.id].tone,
                "next_visit_date": visits[school.id].next_date,
                "training_status": training[school.id].label,
                "training_planned": training[school.id].planned,
                "partner_status": partner_rows.get(school.id, "Not assigned"),
            }
        )
    return rows


def schools_awaiting_project_planning(coordinator_staff_id: str, *, limit: int = 10):
    """Project schools with no project activity planned yet, for the To-Do."""
    from apps.activities.models import Activity
    from apps.projects.models import (
        OPEN_PROJECT_STATUSES,
        Project,
        ProjectSchoolAssignment,
    )

    projects = Project.objects.filter(
        deleted_at__isnull=True,
        status__in=[status.value for status in OPEN_PROJECT_STATUSES],
    ).filter(
        Q(manager_staff_id=coordinator_staff_id)
        | Q(
            staff_assignments__staff_id=coordinator_staff_id,
            staff_assignments__is_active=True,
        )
    )
    project_ids = list(projects.values_list("id", flat=True).distinct())
    if not project_ids:
        return []
    enrolled = list(
        ProjectSchoolAssignment.objects.filter(project_id__in=project_ids)
        .select_related("school", "project")
        .order_by("-created_at")[: limit * 5]
    )
    if not enrolled:
        return []
    planned_pairs = set(
        Activity.objects.filter(
            project_id__in=project_ids,
            school_id__in=[a.school_id for a in enrolled],
            deleted_at__isnull=True,
        )
        .exclude(status__in=("cancelled", "rejected", "not_planned"))
        .values_list("project_id", "school_id")
    )
    return [a for a in enrolled if (a.project_id, a.school_id) not in planned_pairs][
        :limit
    ]


__all__ = ["portfolio_rows", "schools_awaiting_project_planning"]
