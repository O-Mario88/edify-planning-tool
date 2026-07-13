"""Special Projects Planning — coordinator-scoped planning queue.

Project schools land here from the School Directory (Assign to Project). The
coordinator schedules an activity or assigns a partner — both stamp the
activity with `project_id` (via the project-aware planning drawers) so the work
flows into My Plan / Partner Planning and back into the project dashboard and
analytics. Same engine as normal planning, framed by project.
"""

from __future__ import annotations

from django.db.models import Sum

from apps.core.enums import SsaIntervention
from apps.core.fy import get_fy_date_range, get_operational_fy
from apps.core.scoping import resolve_user_scope

from .dashboard_service import _fmt_ugx
from .models import Project, ProjectSchoolAssignment

INTERVENTION_LABELS = dict(SsaIntervention.choices)
CATEGORY_LABELS = {
    "intervention_specific": "Intervention Specific",
    "pilot": "Pilot",
    "selective_limited": "Selective Limited",
}


def _readiness(ssa_status, planning_readiness):
    """Map stored school fields → (baseline_label, baseline_tone, readiness_label,
    readiness_tone, recommended_action, bucket)."""
    if ssa_status == "not_done":
        return (
            "No Baseline",
            "danger",
            "Baseline Required",
            "warning",
            "Schedule Baseline SSA Visit",
            "baseline",
        )
    baseline = ("Baseline Complete", "success")
    if planning_readiness == "in_my_plan":
        return (*baseline, "In My Plan", "info", "View in My Plan", "scheduled")
    if planning_readiness == "scheduled":
        return (*baseline, "Scheduled", "success", "View School", "scheduled")
    if planning_readiness == "ready_for_partner_assignment":
        return (
            *baseline,
            "Assigned to Partner",
            "purple",
            "Monitor Partner Scheduling",
            "partner",
        )
    if planning_readiness == "requires_cluster":
        return (*baseline, "Cluster Required", "neutral", "Add to Cluster", "ready")
    return (*baseline, "Ready for Scheduling", "success", "Schedule Activity", "ready")


def _weakest_intervention(school):
    """Real weakest intervention from the school's latest SSA (or 'Not Assessed')."""
    latest = (
        school.ssa_records.filter(deleted_at__isnull=True)
        .order_by("-date_of_ssa")
        .first()
    )
    if not latest:
        return "Not Assessed"
    scores = sorted(
        latest.scores.all().values("intervention", "score"), key=lambda s: s["score"]
    )
    if not scores:
        return "Not Assessed"
    return INTERVENTION_LABELS.get(scores[0]["intervention"], scores[0]["intervention"])


def get_planning(principal, filters=None) -> dict:
    from apps.activities.models import Activity

    scope = resolve_user_scope(principal)
    fy = get_operational_fy()

    projects_qs = Project.objects.filter(deleted_at__isnull=True)
    if not scope.country_scope:
        staff_id = getattr(principal, "staff_profile_id", None)
        projects_qs = (
            projects_qs.filter(manager_staff_id=staff_id)
            if staff_id
            else projects_qs.none()
        )
    projects = list(projects_qs.order_by("name"))
    project_ids = [p.id for p in projects]
    project_by_id = {p.id: p for p in projects}

    psa = list(
        ProjectSchoolAssignment.objects.filter(project_id__in=project_ids)
        .select_related("school", "school__district")
        .order_by("school__name")
    )
    acts = Activity.objects.filter(deleted_at__isnull=True, project_id__in=project_ids)

    # Current partner per school (latest partner-delivered project activity).
    partner_by_school: dict[str, str] = {}
    for a in (
        acts.filter(delivery_type="partner")
        .exclude(assigned_partner_id__isnull=True)
        .values("school_id", "assigned_partner_id")
    ):
        partner_by_school[a["school_id"]] = a["assigned_partner_id"]
    from apps.partners.models import Partner

    partner_names = {
        p.id: p.name
        for p in Partner.objects.filter(id__in=set(partner_by_school.values()))
    }

    # ── Rows + band/tab counts (readiness from stored fields — no per-row query) ─
    rows = []
    bands = {"baseline": 0, "ready": 0, "partner": 0, "scheduled": 0}
    for a in psa:
        s = a.school
        if not s:
            continue
        (bl, bl_tone, rl, rl_tone, action, bucket) = _readiness(
            s.current_fy_ssa_status, s.planning_readiness
        )
        bands[bucket] = bands.get(bucket, 0) + 1
        proj = project_by_id.get(a.project_id)
        rows.append(
            {
                "school_pk": s.id,
                "school_id": s.school_id,
                "school_name": s.name,
                "district": s.district.name if s.district_id else "—",
                "project_id": a.project_id,
                "project_name": proj.name if proj else "—",
                "project_type": a.project_type
                or (CATEGORY_LABELS.get(proj.category, "—") if proj else "—"),
                "school_type": s.get_school_type_display(),
                "baseline_status": bl,
                "baseline_tone": bl_tone,
                "readiness": rl,
                "readiness_tone": rl_tone,
                "action": action,
                "bucket": bucket,
                "partner": partner_names.get(partner_by_school.get(s.id), "—"),
            }
        )
    # Weakest intervention only for the first page (bounded queries).
    for r in rows[:25]:
        school = next((a.school for a in psa if a.school_id == r["school_pk"]), None)
        r["weakest"] = _weakest_intervention(school) if school else "Not Assessed"

    total = len(rows)
    # ── Scheduled this week ────────────────────────────────────────────────────
    from datetime import timedelta

    from django.utils import timezone

    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    scheduled_week = acts.filter(
        status="scheduled", planned_date__range=(week_start, week_end)
    ).count()

    in_plan_or_scheduled = bands["scheduled"]
    completion = round(in_plan_or_scheduled / total * 100) if total else 0

    # High-risk = no baseline; follow-up = returned / evidence-pending activities.
    high_risk = bands["baseline"]
    requiring_followup = acts.filter(
        status__in=["returned", "returned_by_pl", "returned_by_ia", "in_progress"]
    ).count()

    kpis = [
        {
            "label": "Total Project Schools",
            "value": str(total),
            "icon": "school",
            "variant": "primary",
            "helper": "Ready for planning",
        },
        {
            "label": "Without Baseline / SSA",
            "value": str(bands["baseline"]),
            "icon": "warning",
            "variant": "warning",
            "helper": "Need baseline",
        },
        {
            "label": "Assigned to Partner",
            "value": str(bands["partner"]),
            "icon": "users",
            "variant": "analytics",
            "helper": "Pending schedule",
        },
        {
            "label": "Scheduled This Week",
            "value": str(scheduled_week),
            "icon": "calendar",
            "variant": "info",
            "helper": "In the plan",
        },
        {
            "label": "Schools in Projects",
            "value": str(len({a.school_id for a in psa})),
            "icon": "briefcase",
            "variant": "primary",
            "helper": "Active cohorts",
        },
        {
            "label": "Planning Completion",
            "value": f"{completion}%",
            "icon": "chart",
            "variant": "success",
            "helper": "Scheduled / total",
        },
        {
            "label": "High-Risk Schools",
            "value": str(high_risk),
            "icon": "danger",
            "variant": "danger",
            "helper": "No baseline",
        },
        {
            "label": "Requiring Follow-up",
            "value": str(requiring_followup),
            "icon": "clock",
            "variant": "warning",
            "helper": "Returned / in progress",
        },
    ]

    # ── Readiness bands (3 headline cards) ─────────────────────────────────────
    band_cards = [
        {
            "label": "Baseline Required",
            "value": bands["baseline"],
            "pct": round(bands["baseline"] / total * 100) if total else 0,
            "tone": "danger",
        },
        {
            "label": "Ready for Scheduling",
            "value": bands["ready"],
            "pct": round(bands["ready"] / total * 100) if total else 0,
            "tone": "warning",
        },
        {
            "label": "Ready for Partner Assignment",
            "value": bands["partner"],
            "pct": round(bands["partner"] / total * 100) if total else 0,
            "tone": "success",
        },
    ]

    # ── Project planning summary (per project) ─────────────────────────────────
    summary = []
    for p in projects:
        p_rows = [r for r in rows if r["project_id"] == p.id]
        n = len(p_rows)
        baseline_n = sum(1 for r in p_rows if r["bucket"] == "baseline")
        partner_n = sum(1 for r in p_rows if r["bucket"] == "partner")
        sched_n = sum(1 for r in p_rows if r["bucket"] == "scheduled")
        ready_n = sum(1 for r in p_rows if r["bucket"] == "ready")
        summary.append(
            {
                "name": p.name,
                "assigned": n,
                "ready": ready_n + sched_n,
                "ready_pct": round((ready_n + sched_n) / n * 100) if n else 0,
                "baseline": baseline_n,
                "partner": partner_n,
                "scheduled": sched_n,
            }
        )

    # ── Delivery readiness cards ───────────────────────────────────────────────
    visit_pending = acts.filter(
        activity_type__in=["school_visit", "follow_up_visit", "coaching_visit"],
        status="scheduled",
    ).count()
    training_pending = acts.filter(
        activity_type__in=["training", "cluster_training"], status="scheduled"
    ).count()
    delivery = [
        {"label": "No Baseline", "value": bands["baseline"], "tone": "danger"},
        {"label": "Visit Pending", "value": visit_pending, "tone": "warning"},
        {"label": "Training Pending", "value": training_pending, "tone": "info"},
        {
            "label": "Partner Assignment Pending",
            "value": bands["partner"],
            "tone": "analytics",
        },
        {"label": "High-Risk Schools", "value": high_risk, "tone": "danger"},
    ]

    # Budget generated by these project activities (context).
    from apps.activities.models import ActivityScheduleCostLine

    budget = (
        ActivityScheduleCostLine.objects.filter(
            activity__project_id__in=project_ids
        ).aggregate(n=Sum("amount"))["n"]
        or 0
    )

    return {
        "kpis": kpis,
        "band_cards": band_cards,
        "rows": rows[:25],
        "total": total,
        "tab_counts": {
            "all": total,
            "baseline": bands["baseline"],
            "ready": bands["ready"],
            "partner": bands["partner"],
            "scheduled": bands["scheduled"],
        },
        "summary": summary,
        "delivery": delivery,
        "budget": _fmt_ugx(budget),
        "fy": fy,
        "fy_range": get_fy_date_range(fy),
        "has_projects": bool(project_ids),
    }
