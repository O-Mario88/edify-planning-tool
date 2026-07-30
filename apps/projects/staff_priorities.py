"""Read-only Project priority projections for staff performance surfaces."""

from __future__ import annotations

from collections import defaultdict

from django.db.models import Q

from apps.accounts.models import (
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.activities.models import Activity
from apps.core.enums import SchoolType, SsaIntervention

from .models import LIVE_PROJECT_STATUSES, ProjectSchoolAssignment, ProjectStaffAssignment


COMPLETED_STATES = {
    "ia_verified",
    "accountant_confirmed",
    "completed",
    "closed",
}
INTERVENTION_LABELS = dict(SsaIntervention.choices)
PARTNER_TYPE_LABELS = dict(SchoolType.choices)


def project_priorities_for_users(*, users, fy: str) -> dict[str, list[dict]]:
    """Return assigned Project priorities for several users in bounded queries."""

    users = [
        user for user in users if getattr(user, "staff_profile_id", None)
    ]
    if not users:
        return {}
    users_by_staff = {str(user.staff_profile_id): user for user in users}
    staff_ids = list(users_by_staff)
    assignments = list(
        ProjectStaffAssignment.objects.filter(
            staff_id__in=staff_ids,
            fy=fy,
            is_active=True,
            project__deleted_at__isnull=True,
            project__status__in=[status.value for status in LIVE_PROJECT_STATUSES],
        )
        .select_related("project", "staff__user")
        .order_by("project__name", "staff__user__name")
    )
    if not assignments:
        return {str(user.id): [] for user in users}

    supervised_by_staff: dict[str, set[str]] = defaultdict(set)
    for supervisor_id, supervisee_id in StaffSupervisorAssignment.objects.filter(
        supervisor_id__in=staff_ids
    ).values_list("supervisor_id", "supervisee_id"):
        supervised_by_staff[str(supervisor_id)].add(str(supervisee_id))

    portfolio_staff_ids = set(staff_ids)
    for supervisee_ids in supervised_by_staff.values():
        portfolio_staff_ids.update(supervisee_ids)
    school_ids_by_staff: dict[str, set[str]] = defaultdict(set)
    for staff_id, school_id in StaffSchoolAssignment.objects.filter(
        staff_id__in=portfolio_staff_ids
    ).values_list("staff_id", "school_id"):
        school_ids_by_staff[str(staff_id)].add(str(school_id))

    portfolio_schools_by_staff: dict[str, set[str]] = {}
    for staff_id in staff_ids:
        school_ids = set(school_ids_by_staff.get(staff_id, set()))
        for supervisee_id in supervised_by_staff.get(staff_id, set()):
            school_ids.update(school_ids_by_staff.get(supervisee_id, set()))
        portfolio_schools_by_staff[staff_id] = school_ids

    project_ids = {assignment.project_id for assignment in assignments}
    school_rows = list(
        ProjectSchoolAssignment.objects.filter(
            project_id__in=project_ids,
        ).values(
            "project_id",
            "school_id",
            "school__school_type",
        )
    )
    school_counts: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"all": 0, **{value: 0 for value in PARTNER_TYPE_LABELS}}
    )
    for assignment in assignments:
        key = (str(assignment.project_id), str(assignment.staff_id))
        portfolio = portfolio_schools_by_staff.get(str(assignment.staff_id), set())
        for school in school_rows:
            if (
                str(school["project_id"]) != str(assignment.project_id)
                or str(school["school_id"]) not in portfolio
            ):
                continue
            school_counts[key]["all"] += 1
            partner_type = school["school__school_type"]
            if partner_type in PARTNER_TYPE_LABELS:
                school_counts[key][partner_type] += 1

    owner_to_staff: dict[str, set[str]] = defaultdict(set)
    for staff_id, user in users_by_staff.items():
        owner_to_staff[staff_id].add(staff_id)
        owner_to_staff[str(user.id)].add(staff_id)
    activities = (
        Activity.objects.filter(
            project_id__in=project_ids,
            fy=fy,
            deleted_at__isnull=True,
        )
        .filter(
            Q(responsible_staff_id__in=owner_to_staff)
            | Q(monitored_by_staff_id__in=owner_to_staff)
        )
        .values(
            "project_id",
            "status",
            "responsible_staff_id",
            "monitored_by_staff_id",
        )
    )
    activity_counts: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"planned": 0, "completed": 0}
    )
    for activity in activities:
        matched_staff = set()
        matched_staff.update(
            owner_to_staff.get(str(activity["responsible_staff_id"] or ""), set())
        )
        matched_staff.update(
            owner_to_staff.get(str(activity["monitored_by_staff_id"] or ""), set())
        )
        for staff_id in matched_staff:
            key = (str(activity["project_id"]), staff_id)
            activity_counts[key]["planned"] += 1
            activity_counts[key]["completed"] += int(
                activity["status"] in COMPLETED_STATES
            )

    result: dict[str, list[dict]] = {
        str(user.id): [] for user in users
    }
    for assignment in assignments:
        staff_id = str(assignment.staff_id)
        user = users_by_staff[staff_id]
        key = (str(assignment.project_id), staff_id)
        schools = school_counts[key]
        activity = activity_counts[key]
        result[str(user.id)].append(
            {
                "assignmentId": assignment.id,
                "projectId": assignment.project_id,
                "projectName": assignment.project.name,
                "projectCode": assignment.project.code,
                "schoolFocus": assignment.project.get_school_focus_display(),
                "responsibility": assignment.get_responsibility_display(),
                "targetInterventions": [
                    INTERVENTION_LABELS.get(code, code.replace("_", " ").title())
                    for code in assignment.project.target_intervention_list()
                ],
                "schoolCount": schools["all"],
                "clientSchoolCount": schools["client"],
                "coreSchoolCount": schools["core"],
                "schoolTypeBreakdown": [
                    {
                        "value": value,
                        "label": label,
                        "count": schools[value],
                    }
                    for value, label in SchoolType.choices
                    if schools[value]
                ],
                "activityCount": activity["planned"],
                "completedActivityCount": activity["completed"],
                "progress": (
                    round(activity["completed"] / activity["planned"] * 100)
                    if activity["planned"]
                    else 0
                ),
                "status": (
                    "In progress"
                    if activity["planned"]
                    else "Schools needed"
                    if not schools["all"]
                    else "Ready to plan"
                ),
                "planningUrl": (
                    f"/projects/planning?project={assignment.project_id}&fy={fy}"
                ),
                "assignedByRole": assignment.assigned_by_role,
                "startDate": assignment.start_date,
                "dueDate": assignment.due_date,
            }
        )
    return result


def staff_project_priorities(*, user, fy: str) -> list[dict]:
    return project_priorities_for_users(users=[user], fy=fy).get(
        str(user.id), []
    )


def team_project_priorities(*, users, fy: str) -> list[dict]:
    by_user = project_priorities_for_users(users=users, fy=fy)
    rows = []
    for user in users:
        for priority in by_user.get(str(user.id), []):
            rows.append(
                {
                    **priority,
                    "teamMember": user.name,
                    "teamMemberId": user.id,
                }
            )
    return rows


__all__ = [
    "project_priorities_for_users",
    "staff_project_priorities",
    "team_project_priorities",
]
