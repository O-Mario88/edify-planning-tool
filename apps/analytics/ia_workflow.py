"""Scoped IA outcome review and collection readiness over recorded project evidence."""

from collections import Counter
from statistics import mean

from django.utils import timezone

from apps.core.enums import SsaIntervention
from apps.core.scoping import resolve_user_scope, scoped_school_queryset
from apps.projects.models import ProjectSchoolAssignment
from apps.projects.ssa_impact import MEASURED


LIMITATION = (
    "Recorded project-school assessments only; schools may occur in several projects. "
    "SSA scores are school-level proxies, not direct proof of student transformation "
    "or causal programme effects. Missing evidence is excluded from measured outcomes. "
    "Results use stored classifications and mapping versions, not a new evaluation."
)


def evidence_row(assignment, today):
    baseline = assignment.baseline_ssa
    follow_up = assignment.follow_up_ssa
    valid_baseline = (
        baseline is not None
        and baseline.deleted_at is None
        and baseline.verification_status == "confirmed"
        and baseline.school_id == assignment.school_id
        and baseline.date_of_ssa.date() <= today
        and assignment.baseline_score is not None
        and 0 <= assignment.baseline_score <= 10
    )
    valid_follow_up = (
        follow_up is not None
        and follow_up.deleted_at is None
        and follow_up.verification_status == "confirmed"
        and follow_up.school_id == assignment.school_id
        and follow_up.date_of_ssa.date() <= today
        and assignment.follow_up_score is not None
        and 0 <= assignment.follow_up_score <= 10
        and valid_baseline
        and follow_up.date_of_ssa > baseline.date_of_ssa
    )
    measured = valid_follow_up and assignment.impact_classification in MEASURED
    due = assignment.follow_up_due_on
    if not valid_baseline:
        state, action = "baseline_missing", "Collect or confirm the baseline"
    elif measured:
        state, action = (
            assignment.impact_classification,
            "Review findings with the school",
        )
    elif follow_up is not None:
        state, action = (
            "evidence_review",
            "Review follow-up evidence and classification",
        )
    elif due is None:
        state, action = (
            "not_scheduled",
            "Review verified delivery and set the follow-up window",
        )
    elif due < today:
        state, action = "overdue", "Coordinate the overdue follow-up"
    elif due == today:
        state, action = "due", "Collect the follow-up assessment"
    else:
        state, action = "upcoming", "Prepare the follow-up assessment"
    intervention = (
        assignment.matched_intervention or assignment.project.intervention or ""
    )
    return {
        "school_id": assignment.school_id,
        "school": assignment.school.name,
        "owner_id": assignment.school.account_owner_id or "",
        "project_id": assignment.project_id,
        "project": assignment.project.name,
        "intervention": dict(SsaIntervention.choices).get(intervention, "Not mapped"),
        "state": state,
        "status": state.replace("_", " ").capitalize(),
        "action": action,
        "baseline": assignment.baseline_score if valid_baseline else None,
        "follow_up": assignment.follow_up_score if valid_follow_up else None,
        "baseline_id": assignment.baseline_ssa_id if valid_baseline else "",
        "follow_up_id": assignment.follow_up_ssa_id if valid_follow_up else "",
        "baseline_date": baseline.date_of_ssa.date().isoformat()
        if valid_baseline
        else "",
        "follow_up_date": follow_up.date_of_ssa.date().isoformat()
        if valid_follow_up
        else "",
        "due": due.isoformat() if due else "",
        "mapping_version": assignment.mapping_version,
        "measured": bool(measured),
        "delta": round(assignment.follow_up_score - assignment.baseline_score, 2)
        if measured
        else None,
    }


def outcome_workspace(user, query):
    scope = resolve_user_scope(user)
    schools = scoped_school_queryset(scope)
    # Summary-only authority never authorises this school-identifiable worklist.
    if scope.can_view_summary_only:
        schools = schools.none()
    assignments = ProjectSchoolAssignment.objects.filter(
        school__in=schools, project__deleted_at__isnull=True
    ).select_related("school", "project", "baseline_ssa", "follow_up_ssa")
    projects = list(
        assignments.order_by("project__name")
        .values("project_id", "project__name")
        .distinct()
    )
    project = query.get("project", "")
    if project:
        assignments = assignments.filter(project_id=project)
    rows = [
        evidence_row(row, timezone.localdate())
        for row in assignments.order_by(
            "follow_up_due_on", "school__name", "project_id"
        )
    ]
    from apps.accounts.models import StaffProfile

    owners = dict(
        StaffProfile.objects.filter(
            id__in={row["owner_id"] for row in rows if row["owner_id"]},
            deleted_at__isnull=True,
        ).values_list("id", "user__name")
    )
    for row in rows:
        row["owner"] = owners.get(
            row["owner_id"], "Unassigned — coordinate with programme lead"
        )
    counts = Counter(row["state"] for row in rows)
    measured = [row for row in rows if row["measured"]]
    domains = []
    for label in dict(SsaIntervention.choices).values():
        pairs = [row for row in measured if row["intervention"] == label]
        domains.append(
            {
                "name": label,
                "pairs": len(pairs),
                "delta": round(mean(row["delta"] for row in pairs), 2)
                if pairs
                else None,
            }
        )
    return {
        "rows": rows,
        "projects": projects,
        "project": project,
        "total": len(rows),
        "measured": len(measured),
        "unmeasured": len(rows) - len(measured),
        "improved": counts["improved"],
        "declined": counts["declined"],
        "maintained": counts["maintained_strong"],
        "no_change": counts["no_change"],
        "baseline_missing": counts["baseline_missing"],
        "overdue": counts["overdue"],
        "due": counts["due"],
        "not_scheduled": counts["not_scheduled"],
        "domains": domains,
        "limitation": LIMITATION,
        "generated_at": timezone.now().isoformat(),
        "scope_label": scope.country or "Assigned access scope",
        "period": "All recorded project enrolments; each uses its own assessment window",
    }
