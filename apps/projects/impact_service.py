"""Verified Special Project impact intelligence.

Attribution is deliberately narrow: a project may only claim movement for a
school assigned from the School Directory, after project-stamped delivery, and
only on the project's declared or delivered focus interventions.  SSA movement
uses IA-confirmed records and annual before/after pairs; missing evidence is
reported as not measurable rather than estimated.
"""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlencode

from django.db.models import Q, Sum

from apps.core.enums import ActivityStatus, ActivityType, SsaIntervention
from apps.core.fy import fy_options, get_fy_date_range, get_operational_fy
from apps.analytics.platform_engine import (
    describe_numeric,
    engine_metadata,
    safe_mean,
    trend_analysis,
)

from .dashboard_service import DELIVERED_STATUSES, _fmt_ugx
from .models import ProjectSchoolAssignment
from .planning_service import _scoped_projects


INTERVENTION_LABELS = dict(SsaIntervention.choices)
INTERVENTION_ABBR = {
    "christlike_behaviour": "CB",
    "exposure_to_word_of_god": "WOG",
    "financial_health": "FH",
    "leadership": "Lship",
    "learning_environment": "LE",
    "government_requirement": "GR",
    "teaching_environment": "TE",
    "enrolment": "Enrol.",
}
CLASS_TONE = {
    "Great Impact": "success",
    "Positive Impact": "success",
    "No Measurable Impact": "neutral",
    "Negative Impact": "danger",
    "Not Measurable Yet": "info",
    "Insufficient Data": "info",
}
PROJECT_RECOMMENDATION = {
    "Great Impact": "Scale Project",
    "Positive Impact": "Continue Project",
    "No Measurable Impact": "Redesign Intervention",
    "Negative Impact": "Pause and Review",
    "Not Measurable Yet": "Complete baseline and post-support SSA",
    "Insufficient Data": "Collect more verified SSA",
}
STATUS_FILTERS = {
    "great": {"Great Impact"},
    "positive": {"Positive Impact"},
    "no_impact": {"No Measurable Impact"},
    "negative": {"Negative Impact"},
    "not_measurable": {"Not Measurable Yet", "Insufficient Data"},
}
MIN_MEASURABLE_SCHOOLS = 3
MIN_PARTNER_ACTIVITIES = 3


def _clean_choice(value, allowed, default=""):
    value = str(value or "").strip()
    return value if value in allowed else default


def _collect_ssa_deltas(school_ids, interventions, fy):
    """Annual verified before/after movement for school × intervention pairs.

    Baseline is the most recent confirmed score before the FY, falling back to
    the first confirmed score within the FY. Latest must be a later confirmed
    score inside the selected FY. This prevents old, unrelated movement from
    being presented as the selected year's project impact.
    """
    from apps.ssa.models import SsaScore

    school_ids = set(school_ids or [])
    interventions = set(interventions or [])
    empty = {
        "baseline_avg": None,
        "latest_avg": None,
        "delta": None,
        "measurable_pairs": 0,
        "measurable_schools": 0,
        "improved_schools": set(),
        "declined_schools": set(),
        "pairs": [],
    }
    if not school_ids or not interventions:
        return empty

    fy_start, fy_end = get_fy_date_range(fy)
    rows = list(
        SsaScore.objects.filter(
            ssa_record__school_id__in=school_ids,
            intervention__in=interventions,
            ssa_record__verification_status="confirmed",
            ssa_record__deleted_at__isnull=True,
            ssa_record__date_of_ssa__lt=fy_end,
        )
        .values_list(
            "ssa_record__school_id",
            "intervention",
            "score",
            "ssa_record__date_of_ssa",
        )
        .order_by("ssa_record__date_of_ssa")
    )
    grouped = defaultdict(list)
    for school_id, intervention, score, collected_at in rows:
        grouped[(school_id, intervention)].append((collected_at, float(score)))

    pairs = []
    improved, declined = set(), set()
    for (school_id, intervention), scores in grouped.items():
        before = [item for item in scores if item[0] < fy_start]
        within = [item for item in scores if fy_start <= item[0] < fy_end]
        if not within:
            continue
        baseline = before[-1] if before else within[0]
        latest = within[-1]
        if latest[0] <= baseline[0]:
            continue
        delta = latest[1] - baseline[1]
        pair = {
            "school_id": school_id,
            "intervention": intervention,
            "baseline": baseline[1],
            "latest": latest[1],
            "delta": delta,
        }
        pairs.append(pair)
        if delta > 0.05:
            improved.add(school_id)
        elif delta < -0.05:
            declined.add(school_id)

    if not pairs:
        return empty
    return {
        "baseline_avg": round(sum(pair["baseline"] for pair in pairs) / len(pairs), 2),
        "latest_avg": round(sum(pair["latest"] for pair in pairs) / len(pairs), 2),
        "delta": round(sum(pair["delta"] for pair in pairs) / len(pairs), 2),
        "measurable_pairs": len(pairs),
        "measurable_schools": len({pair["school_id"] for pair in pairs}),
        "improved_schools": improved,
        "declined_schools": declined,
        "pairs": pairs,
    }


def _classify_project(delta, delivery_rate, measurable_schools):
    if measurable_schools == 0:
        return "Not Measurable Yet"
    if measurable_schools < MIN_MEASURABLE_SCHOOLS:
        return "Insufficient Data"
    if delta is None:
        return "Not Measurable Yet"
    if delta >= 1.5 and delivery_rate >= 0.85:
        return "Great Impact"
    if delta >= 0.5:
        return "Positive Impact"
    if delta <= -0.5:
        return "Negative Impact"
    return "No Measurable Impact"


def _impact_score(delta, delivery_rate, measurable):
    if delta is None or not measurable:
        return None
    movement = max(0.0, min(1.0, (delta + 1.0) / 3.0))
    return round((movement * 0.7 + max(0.0, min(1.0, delivery_rate)) * 0.3) * 100)


def _partner_score(delta, delivery_rate, ia_rate, evidence_rate, timeliness, cost_rate):
    movement = 0 if delta is None else max(0.0, min(1.0, (delta + 1.0) / 2.5))
    value = (
        movement * 0.35
        + delivery_rate * 0.24
        + ia_rate * 0.12
        + evidence_rate * 0.12
        + timeliness * 0.12
        + cost_rate * 0.05
    )
    return round(max(0.0, min(1.0, value)) * 100)


def _classify_partner(score, completed, measurable_schools):
    if completed < MIN_PARTNER_ACTIVITIES or measurable_schools < 2:
        return "Insufficient Data", "info"
    if score >= 85:
        return "Scale Up", "success"
    if score >= 70:
        return "Keep Active", "success"
    if score >= 50:
        return "Under Review", "warning"
    return "Drop / Do Not Renew", "danger"


def _conic_gradient(distribution):
    colors = {
        "Great Impact": "#14965c",
        "Positive Impact": "#76c95f",
        "No Measurable Impact": "#cbd5e1",
        "Negative Impact": "#ef5b62",
        "Not Measurable Yet": "#8ab6e8",
        "Insufficient Data": "#bdd8f4",
    }
    total = sum(item[1] for item in distribution)
    if not total:
        return "conic-gradient(#e2e8f0 0deg 360deg)"
    cursor = 0.0
    segments = []
    for label, value in distribution:
        end = cursor + value / total * 360
        segments.append(f"{colors[label]} {cursor:.1f}deg {end:.1f}deg")
        cursor = end
    return f"conic-gradient({', '.join(segments)})"


def _supported_school_ids(activity, assigned_ids):
    """Schools a project activity may influence, capped to its assigned cohort."""
    school_ids = set()
    if activity.school_id:
        school_ids.add(activity.school_id)
    school_ids.update(activity.attended_school_ids or [])
    return school_ids & set(assigned_ids)


def get_analytics(principal, filters=None) -> dict:
    from apps.activities.models import Activity, ActivityScheduleCostLine
    from apps.geography.models import District, Region
    from apps.partners.models import Partner
    from apps.ssa.models import SsaRecord

    filters = filters or {}
    selected_fy = _clean_choice(
        filters.get("fy"), set(fy_options()), get_operational_fy()
    )
    selected_region = str(filters.get("region") or "").strip()
    selected_district = str(filters.get("district") or "").strip()
    selected_project = str(filters.get("project") or "").strip()
    selected_partner = str(filters.get("partner") or "").strip()
    selected_intervention = _clean_choice(
        filters.get("intervention"), set(INTERVENTION_LABELS)
    )
    selected_status = _clean_choice(filters.get("impact_status"), set(STATUS_FILTERS))
    search = str(filters.get("q") or "").strip()

    scoped_projects = list(_scoped_projects(principal))
    scoped_project_ids = [project.id for project in scoped_projects]
    scoped_assignments = ProjectSchoolAssignment.objects.filter(
        project_id__in=scoped_project_ids
    ).select_related("school", "school__region", "school__district", "project")

    region_options = (
        Region.objects.filter(
            id__in=scoped_assignments.values_list("school__region_id", flat=True)
        )
        .distinct()
        .order_by("name")
    )
    district_options = (
        District.objects.filter(
            id__in=scoped_assignments.values_list("school__district_id", flat=True)
        )
        .distinct()
        .order_by("name")
    )
    if selected_region:
        district_options = district_options.filter(region_id=selected_region)

    assignments = scoped_assignments
    if selected_region:
        assignments = assignments.filter(school__region_id=selected_region)
    if selected_district:
        assignments = assignments.filter(school__district_id=selected_district)
    if selected_project in scoped_project_ids:
        assignments = assignments.filter(project_id=selected_project)
    else:
        selected_project = ""

    activity_scope = Activity.objects.filter(
        deleted_at__isnull=True,
        project_id__in=scoped_project_ids,
    ).filter(Q(fy=selected_fy) | Q(fiscal_year=selected_fy))
    partner_ids_all = set(
        activity_scope.exclude(assigned_partner_id__isnull=True)
        .exclude(assigned_partner_id="")
        .values_list("assigned_partner_id", flat=True)
    )
    partner_options = Partner.objects.filter(id__in=partner_ids_all).order_by("name")
    if selected_partner not in partner_ids_all:
        selected_partner = ""

    candidate_ids = set(assignments.values_list("project_id", flat=True))
    if selected_partner:
        candidate_ids &= set(
            activity_scope.filter(assigned_partner_id=selected_partner).values_list(
                "project_id", flat=True
            )
        )
    if selected_intervention:
        focused_project_ids = set(
            activity_scope.filter(focus_intervention=selected_intervention).values_list(
                "project_id", flat=True
            )
        )
        declared_project_ids = {
            project.id
            for project in scoped_projects
            if project.intervention == selected_intervention
        }
        candidate_ids &= focused_project_ids | declared_project_ids
    if search:
        matching_partner_ids = set(
            Partner.objects.filter(name__icontains=search).values_list("id", flat=True)
        )
        search_projects = set(
            scoped_assignments.filter(
                Q(project__name__icontains=search)
                | Q(school__name__icontains=search)
                | Q(school__school_id__icontains=search)
                | Q(school__district__name__icontains=search)
            ).values_list("project_id", flat=True)
        )
        if matching_partner_ids:
            search_projects |= set(
                activity_scope.filter(
                    assigned_partner_id__in=matching_partner_ids
                ).values_list("project_id", flat=True)
            )
        candidate_ids &= search_projects

    projects = [project for project in scoped_projects if project.id in candidate_ids]
    project_ids = [project.id for project in projects]
    assignments = list(assignments.filter(project_id__in=project_ids))
    activities = list(
        activity_scope.filter(project_id__in=project_ids)
        .exclude(
            status__in=[
                ActivityStatus.CANCELLED,
                ActivityStatus.REJECTED,
                ActivityStatus.DEFERRED,
            ]
        )
        .select_related("school")
        .order_by("planned_date", "created_at")
    )
    if selected_partner:
        activities = [
            activity
            for activity in activities
            if activity.assigned_partner_id == selected_partner
        ]

    schools_by_project = defaultdict(set)
    school_objects = {}
    for assignment in assignments:
        schools_by_project[assignment.project_id].add(assignment.school_id)
        school_objects[assignment.school_id] = assignment.school

    # Impact reporting is downstream of the planning intake. A project stamp by
    # itself is not enough: the activity must also reach at least one school in
    # that project's School Directory assignment cohort.
    activities = [
        activity
        for activity in activities
        if _supported_school_ids(activity, schools_by_project[activity.project_id])
    ]
    acts_by_project = defaultdict(list)
    for activity in activities:
        acts_by_project[activity.project_id].append(activity)

    activity_ids = [activity.id for activity in activities]
    budget_rows = ActivityScheduleCostLine.objects.filter(activity_id__in=activity_ids)
    budget_by_project = {
        row["activity__project_id"]: row["total"]
        for row in budget_rows.values("activity__project_id").annotate(
            total=Sum("amount")
        )
    }
    partner_names = {
        partner.id: partner.name
        for partner in Partner.objects.filter(id__in=partner_ids_all)
    }

    project_payloads = []
    for project in projects:
        project_acts = acts_by_project[project.id]
        planned = [
            activity
            for activity in project_acts
            if activity.status != ActivityStatus.NOT_PLANNED
        ]
        delivered = [
            activity
            for activity in project_acts
            if activity.status in DELIVERED_STATUSES
        ]
        supported_ids = (
            set().union(
                *(
                    _supported_school_ids(activity, schools_by_project[project.id])
                    for activity in delivered
                )
            )
            if delivered
            else set()
        )
        declared = {project.intervention} if project.intervention else set()
        delivered_focus = {
            activity.focus_intervention
            for activity in delivered
            if activity.focus_intervention
        }
        interventions = declared | delivered_focus
        if selected_intervention:
            interventions &= {selected_intervention}
        ssa = _collect_ssa_deltas(supported_ids, interventions, selected_fy)
        delivery_rate = len(delivered) / len(planned) if planned else 0
        classification = _classify_project(
            ssa["delta"], delivery_rate, ssa["measurable_schools"]
        )
        intervention_details = []
        for code in sorted(interventions):
            detail = _collect_ssa_deltas(supported_ids, {code}, selected_fy)
            intervention_details.append(
                {
                    "code": code,
                    "label": INTERVENTION_LABELS.get(code, code),
                    "abbr": INTERVENTION_ABBR.get(code, code),
                    **detail,
                }
            )
        budget = budget_by_project.get(project.id, 0) or 0
        project_payloads.append(
            {
                "id": project.id,
                "name": project.name,
                "url": f"/projects/{project.id}",
                "intervention_codes": interventions,
                "interventions": ", ".join(
                    INTERVENTION_ABBR.get(code, code) for code in sorted(interventions)
                )
                or "—",
                "intervention_details": intervention_details,
                "schools_assigned": len(schools_by_project[project.id]),
                "schools_supported": len(supported_ids),
                "supported_ids": supported_ids,
                "planned": len(planned),
                "delivered": len(delivered),
                "delivery_rate": round(delivery_rate * 100),
                "baseline_avg": ssa["baseline_avg"],
                "latest_avg": ssa["latest_avg"],
                "delta": ssa["delta"],
                "measurable_schools": ssa["measurable_schools"],
                "improved_schools": ssa["improved_schools"],
                "declined_schools": ssa["declined_schools"],
                "impact_score": _impact_score(
                    ssa["delta"], delivery_rate, ssa["measurable_schools"]
                ),
                "budget_value": budget,
                "budget": _fmt_ugx(budget),
                "cost_per_improved": _fmt_ugx(
                    round(budget / len(ssa["improved_schools"]))
                )
                if ssa["improved_schools"]
                else "—",
                "classification": classification,
                "tone": CLASS_TONE[classification],
                "recommendation": PROJECT_RECOMMENDATION[classification],
            }
        )

    if selected_status:
        allowed = STATUS_FILTERS[selected_status]
        project_payloads = [
            row for row in project_payloads if row["classification"] in allowed
        ]
    included_project_ids = {row["id"] for row in project_payloads}
    included_activities = [
        activity
        for activity in activities
        if activity.project_id in included_project_ids
    ]

    class_labels = [
        "Great Impact",
        "Positive Impact",
        "No Measurable Impact",
        "Negative Impact",
        "Not Measurable Yet",
        "Insufficient Data",
    ]
    class_counts = {label: 0 for label in class_labels}
    for row in project_payloads:
        class_counts[row["classification"]] += 1
    class_distribution = [(label, class_counts[label]) for label in class_labels]
    class_dist = [
        {
            "label": label,
            "value": value,
            "pct": round(value / max(len(project_payloads), 1) * 100),
            "tone": CLASS_TONE[label],
        }
        for label, value in class_distribution
    ]

    intervention_acc = defaultdict(
        lambda: {"projects": set(), "schools": set(), "pairs": []}
    )
    for row in project_payloads:
        for detail in row["intervention_details"]:
            acc = intervention_acc[detail["code"]]
            acc["projects"].add(row["id"])
            acc["schools"] |= row["supported_ids"]
            acc["pairs"].extend(detail["pairs"])
    interventions = []
    for code, acc in intervention_acc.items():
        pairs = acc["pairs"]
        baseline = (
            round(sum(pair["baseline"] for pair in pairs) / len(pairs), 2)
            if pairs
            else None
        )
        latest = (
            round(sum(pair["latest"] for pair in pairs) / len(pairs), 2)
            if pairs
            else None
        )
        delta = (
            round(sum(pair["delta"] for pair in pairs) / len(pairs), 2)
            if pairs
            else None
        )
        interventions.append(
            {
                "code": code,
                "label": INTERVENTION_LABELS.get(code, code),
                "abbr": INTERVENTION_ABBR.get(code, code),
                "projects": len(acc["projects"]),
                "schools": len(acc["schools"]),
                "measurable": len({pair["school_id"] for pair in pairs}),
                "baseline": baseline,
                "latest": latest,
                "delta": delta,
                "baseline_pct": round((baseline or 0) * 10),
                "latest_pct": round((latest or 0) * 10),
                "tone": "success"
                if (delta or 0) >= 0.5
                else ("danger" if (delta or 0) <= -0.5 else "neutral"),
            }
        )
    interventions.sort(
        key=lambda item: item["delta"] if item["delta"] is not None else -99,
        reverse=True,
    )

    # Partner performance is project-specific; one partner may have a different
    # recommendation in different projects.
    partner_rows = []
    rec_counts = defaultdict(int)
    for row in project_payloads:
        project_acts = [
            activity
            for activity in included_activities
            if activity.project_id == row["id"]
        ]
        project_partner_ids = {
            activity.assigned_partner_id
            for activity in project_acts
            if activity.assigned_partner_id
        }
        for partner_id in project_partner_ids:
            partner_acts = [
                activity
                for activity in project_acts
                if activity.assigned_partner_id == partner_id
            ]
            completed = [
                activity
                for activity in partner_acts
                if activity.status in DELIVERED_STATUSES
            ]
            assigned = [
                activity
                for activity in partner_acts
                if activity.status != ActivityStatus.NOT_PLANNED
            ]
            delivery_rate = len(completed) / len(assigned) if assigned else 0
            evidence_rate = (
                sum(activity.evidence_status == "accepted" for activity in completed)
                / len(completed)
                if completed
                else 0
            )
            ia_submitted = [
                activity
                for activity in partner_acts
                if activity.status in DELIVERED_STATUSES
                or activity.ia_verification_status != "pending"
            ]
            ia_rate = (
                sum(
                    activity.ia_verification_status == "confirmed"
                    or activity.status == "ia_verified"
                    for activity in ia_submitted
                )
                / len(ia_submitted)
                if ia_submitted
                else 0
            )
            timeliness = (
                sum((activity.reschedule_count or 0) == 0 for activity in completed)
                / len(completed)
                if completed
                else 0
            )
            cost_rate = (
                sum(not activity.cost_missing for activity in assigned) / len(assigned)
                if assigned
                else 0
            )
            supported_ids = (
                set().union(
                    *(
                        _supported_school_ids(activity, schools_by_project[row["id"]])
                        for activity in completed
                    )
                )
                if completed
                else set()
            )
            focus = row["intervention_codes"] | {
                activity.focus_intervention
                for activity in partner_acts
                if activity.focus_intervention
            }
            ssa = _collect_ssa_deltas(supported_ids, focus, selected_fy)
            score = _partner_score(
                ssa["delta"],
                delivery_rate,
                ia_rate,
                evidence_rate,
                timeliness,
                cost_rate,
            )
            recommendation, tone = _classify_partner(
                score, len(completed), ssa["measurable_schools"]
            )
            rec_counts[recommendation] += 1
            partner_budget = (
                budget_rows.filter(
                    activity__project_id=row["id"],
                    activity__assigned_partner_id=partner_id,
                ).aggregate(total=Sum("amount"))["total"]
                or 0
            )
            partner_rows.append(
                {
                    "name": partner_names.get(partner_id, "Partner"),
                    "project": row["name"],
                    "project_url": row["url"],
                    "schools_assigned": len(
                        {
                            activity.school_id
                            for activity in partner_acts
                            if activity.school_id
                        }
                    ),
                    "completed": len(completed),
                    "target_achievement": round(delivery_rate * 100),
                    "evidence_rate": round(evidence_rate * 100),
                    "delta": ssa["delta"],
                    "ia_rate": round(ia_rate * 100),
                    "cost_per_improved": _fmt_ugx(
                        round(partner_budget / len(ssa["improved_schools"]))
                    )
                    if ssa["improved_schools"]
                    else "—",
                    "score": score if recommendation != "Insufficient Data" else None,
                    "recommendation": recommendation,
                    "tone": tone,
                }
            )
    partner_rows.sort(
        key=lambda row: row["score"] if row["score"] is not None else -1, reverse=True
    )

    improved_schools = (
        set().union(*(row["improved_schools"] for row in project_payloads))
        if project_payloads
        else set()
    )
    declined_schools = (
        set().union(*(row["declined_schools"] for row in project_payloads))
        if project_payloads
        else set()
    )
    assigned_school_ids = (
        set().union(*(schools_by_project[row["id"]] for row in project_payloads))
        if project_payloads
        else set()
    )
    supported_school_ids = (
        set().union(*(row["supported_ids"] for row in project_payloads))
        if project_payloads
        else set()
    )
    delivered_activities = [
        activity
        for activity in included_activities
        if activity.status in DELIVERED_STATUSES
    ]
    total_budget = sum(row["budget_value"] for row in project_payloads)
    evidence_completion = (
        round(
            sum(
                activity.evidence_status == "accepted"
                for activity in delivered_activities
            )
            / len(delivered_activities)
            * 100
        )
        if delivered_activities
        else 0
    )
    average_delta_values = [
        row["delta"] for row in project_payloads if row["delta"] is not None
    ]
    average_delta = safe_mean(average_delta_values)
    adoption_rate = (
        round(len(supported_school_ids) / len(assigned_school_ids) * 100)
        if assigned_school_ids
        else 0
    )
    teachers = sum(activity.teachers_attended or 0 for activity in delivered_activities)
    leaders = sum(activity.leaders_attended or 0 for activity in delivered_activities)
    students = sum(
        (school_objects[school_id].enrollment or 0)
        for school_id in supported_school_ids
        if school_id in school_objects
    )

    kpis = [
        {
            "label": "Total Projects",
            "value": len(project_payloads),
            "helper": f"FY {selected_fy}",
            "tone": "blue",
            "icon": "folder",
        },
        {
            "label": "Schools in Projects",
            "value": len(assigned_school_ids),
            "helper": f"{len(supported_school_ids)} received verified support",
            "tone": "teal",
            "icon": "school",
        },
        {
            "label": "Great Impact",
            "value": class_counts["Great Impact"],
            "helper": "ready to scale",
            "tone": "green",
            "icon": "chart",
        },
        {
            "label": "Negative Impact",
            "value": class_counts["Negative Impact"],
            "helper": "pause and review",
            "tone": "red",
            "icon": "warning",
        },
        {
            "label": "Teachers Impacted",
            "value": teachers,
            "helper": "verified attendance",
            "tone": "purple",
            "icon": "partner",
        },
        {
            "label": "School Leaders Impacted",
            "value": leaders,
            "helper": "verified attendance",
            "tone": "orange",
            "icon": "partner",
        },
        {
            "label": "Students Reached",
            "value": students,
            "helper": "enrolment at supported schools",
            "tone": "purple",
            "icon": "school",
        },
        {
            "label": "Avg Annual SSA Delta",
            "value": f"{average_delta:+.2f}" if average_delta is not None else "—",
            "helper": "associated interventions",
            "tone": "green",
            "icon": "chart",
        },
        {
            "label": "Delivery Adoption",
            "value": f"{adoption_rate}%",
            "helper": "assigned schools receiving verified support",
            "tone": "blue",
            "icon": "check",
        },
        {
            "label": "Evidence Completion",
            "value": f"{evidence_completion}%",
            "helper": "accepted evidence on delivered work",
            "tone": "teal",
            "icon": "document",
        },
    ]

    # Transparent workflow adoption proxy (not a fabricated adoption survey).
    adoption_rows = []
    for row in project_payloads:
        for school_id in sorted(
            row["supported_ids"],
            key=lambda sid: school_objects[sid].name if sid in school_objects else sid,
        ):
            school_acts = [
                activity
                for activity in delivered_activities
                if activity.project_id == row["id"] and activity.school_id == school_id
            ]
            accepted = sum(
                activity.evidence_status == "accepted" for activity in school_acts
            )
            evidence_rate = accepted / len(school_acts) if school_acts else 0
            school_deltas = [
                pair["delta"]
                for detail in row["intervention_details"]
                for pair in detail["pairs"]
                if pair["school_id"] == school_id
            ]
            school_delta = (
                round(sum(school_deltas) / len(school_deltas), 2)
                if school_deltas
                else None
            )
            if (
                len(school_acts) >= 2
                and evidence_rate >= 0.8
                and (school_delta or 0) >= 0.5
            ):
                adoption, tone = "High", "success"
            elif school_acts and evidence_rate > 0:
                adoption, tone = "Moderate", "warning"
            else:
                adoption, tone = "Low", "danger"
            latest_date = max(
                (
                    activity.planned_date
                    for activity in school_acts
                    if activity.planned_date
                ),
                default=None,
            )
            adoption_rows.append(
                {
                    "school": school_objects[school_id].name
                    if school_id in school_objects
                    else "School",
                    "project": row["name"],
                    "status": adoption,
                    "tone": tone,
                    "evidence": f"{accepted}/{len(school_acts)} accepted",
                    "latest": latest_date,
                    "delta": school_delta,
                }
            )
    adoption_rows.sort(
        key=lambda row: (
            {"Low": 0, "Moderate": 1, "High": 2}[row["status"]],
            row["school"],
        )
    )

    # Four-year overview uses the same annual attribution rule.
    trend = []
    for year in range(max(2025, int(selected_fy) - 3), int(selected_fy) + 1):
        year_fy = str(year)
        year_acts = list(
            Activity.objects.filter(
                deleted_at__isnull=True, project_id__in=included_project_ids
            )
            .filter(Q(fy=year_fy) | Q(fiscal_year=year_fy))
            .filter(status__in=DELIVERED_STATUSES)
        )
        by_project = defaultdict(list)
        for activity in year_acts:
            by_project[activity.project_id].append(activity)
        assessed, year_improved, deltas = 0, set(), []
        for row in project_payloads:
            supported = (
                set().union(
                    *(
                        _supported_school_ids(activity, schools_by_project[row["id"]])
                        for activity in by_project[row["id"]]
                    )
                )
                if by_project[row["id"]]
                else set()
            )
            result = _collect_ssa_deltas(supported, row["intervention_codes"], year_fy)
            if result["measurable_schools"]:
                assessed += 1
                year_improved |= result["improved_schools"]
                deltas.append(result["delta"])
        trend.append(
            {
                "fy": year_fy,
                "projects": assessed,
                "improved": len(year_improved),
                "delta": safe_mean(deltas),
            }
        )
    max_improved = max((item["improved"] for item in trend), default=0) or 1
    for item in trend:
        item["bar_pct"] = (
            max(8, round(item["improved"] / max_improved * 100))
            if item["improved"]
            else 3
        )

    best_projects = sorted(
        [
            row
            for row in project_payloads
            if row["classification"] in {"Great Impact", "Positive Impact"}
        ],
        key=lambda row: row["impact_score"] or -1,
        reverse=True,
    )[:3]
    under_review = [
        row
        for row in project_payloads
        if row["classification"]
        in {"No Measurable Impact", "Insufficient Data", "Not Measurable Yet"}
    ][:3]
    watchlist = [
        row for row in project_payloads if row["classification"] == "Negative Impact"
    ][:3]

    insights = []
    if class_counts["Great Impact"]:
        insights.append(
            {
                "tone": "success",
                "title": f"{class_counts['Great Impact']} project(s) are ready to scale.",
                "detail": ", ".join(row["name"] for row in best_projects),
                "url": "#impact-matrix",
            }
        )
    if rec_counts["Under Review"] or rec_counts["Drop / Do Not Renew"]:
        count = rec_counts["Under Review"] + rec_counts["Drop / Do Not Renew"]
        insights.append(
            {
                "tone": "warning",
                "title": f"{count} partner-project relationship(s) need review.",
                "detail": "Review delivery, evidence, IA verification and SSA movement together.",
                "url": "#partner-performance",
            }
        )
    if class_counts["Negative Impact"]:
        insights.append(
            {
                "tone": "danger",
                "title": f"{class_counts['Negative Impact']} project(s) show negative associated intervention movement.",
                "detail": ", ".join(row["name"] for row in watchlist),
                "url": "#impact-matrix",
            }
        )
    not_measurable = (
        class_counts["Not Measurable Yet"] + class_counts["Insufficient Data"]
    )
    if not_measurable:
        insights.append(
            {
                "tone": "info",
                "title": f"{not_measurable} project(s) cannot yet support an impact decision.",
                "detail": "Finish project delivery, accepted evidence, and confirmed before/after SSA on associated interventions.",
                "url": "/projects/planning",
            }
        )
    if not insights:
        insights.append(
            {
                "tone": "info",
                "title": "No verified impact signal is available for this filter.",
                "detail": "The dashboard will update as the special-project workflow reaches verified delivery and annual SSA follow-up.",
                "url": "/projects/planning",
            }
        )

    rec_dist = [
        {"label": label, "value": rec_counts[label], "tone": tone}
        for label, tone in [
            ("Scale Up", "success"),
            ("Keep Active", "success"),
            ("Under Review", "warning"),
            ("Drop / Do Not Renew", "danger"),
            ("Insufficient Data", "neutral"),
        ]
    ]
    verified_ssa = SsaRecord.objects.filter(
        school_id__in=assigned_school_ids,
        fy=selected_fy,
        verification_status="confirmed",
        deleted_at__isnull=True,
    ).count()
    impact_ready = sum(
        row["classification"] not in {"Not Measurable Yet", "Insufficient Data"}
        for row in project_payloads
    )
    data_quality = {
        "verified_activities": len(delivered_activities),
        "verified_ssa": verified_ssa,
        "evidence_completion": evidence_completion,
        "impact_ready": impact_ready,
        "budget": _fmt_ugx(total_budget),
        "improved_schools": len(improved_schools),
        "declined_schools": len(declined_schools),
    }

    selected = {
        "fy": selected_fy,
        "region": selected_region,
        "district": selected_district,
        "project": selected_project,
        "partner": selected_partner,
        "intervention": selected_intervention,
        "impact_status": selected_status,
        "q": search,
    }
    query = {key: value for key, value in selected.items() if value}
    project_delta_summary = describe_numeric(
        (row["delta"] for row in project_payloads if row.get("delta") is not None),
        target=0.3,
    )
    trend_signal = trend_analysis([item["delta"] for item in trend], stable_slope=0.02)
    return {
        "has_projects": bool(scoped_project_ids),
        "has_results": bool(project_payloads),
        "fy_options": fy_options(),
        "regions": region_options,
        "districts": district_options,
        "projects": scoped_projects,
        "partner_options": partner_options,
        "intervention_options": SsaIntervention.choices,
        "impact_statuses": [
            {"value": "great", "label": "Great Impact"},
            {"value": "positive", "label": "Positive Impact"},
            {"value": "no_impact", "label": "No Measurable Impact"},
            {"value": "negative", "label": "Negative Impact"},
            {"value": "not_measurable", "label": "Not Measurable Yet"},
        ],
        "selected": selected,
        "kpis": kpis,
        "class_dist": class_dist,
        "class_total": len(project_payloads),
        "class_gradient": _conic_gradient(class_distribution),
        "trend": trend,
        "interventions": interventions,
        "partners": partner_rows,
        "matrix": project_payloads,
        "best_projects": best_projects,
        "under_review": under_review,
        "watchlist": watchlist,
        "adoption_rows": adoption_rows[:12],
        "rec_dist": rec_dist,
        "insights": insights,
        "data_quality": data_quality,
        "analytics": {
            "project_delta": project_delta_summary,
            "trend": trend_signal,
            "engine": engine_metadata(
                "special_project_impact",
                record_count=project_delta_summary["count"],
                confirmed_only=True,
            ),
        },
        "donor_snapshot": {
            "teachers": teachers,
            "leaders": leaders,
            "students": students,
            "schools": len(supported_school_ids),
            "districts": len(
                {
                    school_objects[sid].district_id
                    for sid in supported_school_ids
                    if sid in school_objects
                }
            ),
        },
        "activity_type_labels": dict(ActivityType.choices),
        "export_url": f"/projects/analytics?{urlencode({**query, 'export': 'csv'})}",
        "snapshot_url": f"/projects/analytics?{urlencode({**query, 'export': 'snapshot'})}",
    }
