"""Special Projects command-center dashboard — real, scope-constrained aggregation.

Everything here is computed from the live engine (Project / ProjectSchoolAssignment /
ProjectPartnerAssignment / Activity / ActivityScheduleCostLine), scoped to the caller
via `resolve_user_scope`:

  • Project Coordinator → only projects they manage (`Project.manager_staff_id`).
  • Country roles (CD/Admin/IA/Accountant) → all projects.

No fabricated numbers: where a source genuinely does not exist yet the value is 0 / "—".
Derived bands (completion %, status, planning-readiness labels) come from real data.
"""

from __future__ import annotations

from django.db.models import Q, Sum

from apps.core.scoping import resolve_user_scope

from apps.core.activity_types import TRAINING_TYPES, VISIT_TYPES

from .models import (
    Project,
    ProjectCategory,
    ProjectPartnerAssignment,
    ProjectSchoolAssignment,
)


# ── Activity lifecycle groupings (values from apps.core.enums.ActivityStatus) ──
DELIVERED_STATUSES = ["ia_verified", "accountant_confirmed", "completed", "closed"]
NOT_IN_PLAN_STATUSES = ["not_planned", "closed", "cancelled", "rejected", "deferred"]
SSA_TYPES = [
    "ssa_activity",
    "baseline_ssa_visit",
    "partner_ssa_collection",
    "cluster_training_ssa_collection",
    "cluster_meeting_ssa_review",
    "core_assessment_visit",
]


def _fmt_ugx(amount: int | None) -> str:
    """Compact UGX formatter: 2_480_000_000 -> 'UGX 2.48B'."""
    a = int(amount or 0)
    if a >= 1_000_000_000:
        return f"UGX {a / 1_000_000_000:.2f}B"
    if a >= 1_000_000:
        return f"UGX {a / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"UGX {a / 1_000:.0f}K"
    return f"UGX {a:,}"


def _coordinator_name(staff_id: str | None) -> str:
    if not staff_id:
        return "Unassigned"
    try:
        from apps.accounts.models import StaffProfile

        sp = StaffProfile.objects.filter(id=staff_id).select_related("user").first()
        if sp:
            return (
                getattr(sp, "name", None)
                or getattr(getattr(sp, "user", None), "name", None)
                or "Assigned"
            )
    except Exception:  # noqa: BLE001
        pass
    return "Assigned"


def _status_band(completion_pct: int, total_activities: int) -> tuple[str, str]:
    """Derived (not fabricated) delivery status from real completion."""
    if total_activities == 0:
        return "Planning", "neutral"
    if completion_pct >= 60:
        return "On Track", "success"
    if completion_pct >= 30:
        return "At Risk", "warning"
    return "Behind", "danger"


def get_dashboard(principal, selected_project_id: str | None = None) -> dict:
    from apps.activities.models import Activity, ActivityScheduleCostLine

    scope = resolve_user_scope(principal)

    # ── Scoped project set ────────────────────────────────────────────────────
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

    # ── Base querysets (all scoped to those projects) ─────────────────────────
    psa = ProjectSchoolAssignment.objects.filter(
        project_id__in=project_ids
    ).select_related("school", "school__district", "school__region")
    acts = Activity.objects.filter(deleted_at__isnull=True, project_id__in=project_ids)
    lines = ActivityScheduleCostLine.objects.filter(
        activity__project_id__in=project_ids
    )

    school_ids = list({a.school_id for a in psa if a.school_id})
    partner_links = ProjectPartnerAssignment.objects.filter(
        project_id__in=project_ids
    ).select_related("partner")

    # ── Headline KPIs ─────────────────────────────────────────────────────────
    active_project_ids = set(
        acts.exclude(status__in=NOT_IN_PLAN_STATUSES).values_list(
            "project_id", flat=True
        )
    )
    delivered = acts.filter(status__in=DELIVERED_STATUSES)
    delivered_school_ids = set(delivered.values_list("school_id", flat=True))

    teachers_trained = (
        delivered.filter(activity_type__in=TRAINING_TYPES).aggregate(
            n=Sum("teachers_attended")
        )["n"]
        or 0
    )
    leaders_trained = (
        delivered.filter(activity_type__in=TRAINING_TYPES).aggregate(
            n=Sum("leaders_attended")
        )["n"]
        or 0
    )
    from apps.schools.models import School

    learners_reached = (
        School.objects.filter(id__in=delivered_school_ids).aggregate(
            n=Sum("enrollment")
        )["n"]
        or 0
    )
    budget_generated = lines.aggregate(n=Sum("amount"))["n"] or 0
    activities_in_plan = acts.exclude(status__in=NOT_IN_PLAN_STATUSES).count()
    evidence_pending = (
        acts.filter(
            Q(status__in=["in_progress", "completion_started"])
            | Q(evidence_status__in=["uploaded", "returned"])
        )
        .exclude(status__in=["closed", "cancelled", "rejected"])
        .distinct()
        .count()
    )
    ia_pending = (
        acts.filter(
            Q(status="awaiting_ia_verification")
            | Q(status="returned_by_ia")
            | Q(ia_verification_status="flagged")
        )
        .exclude(status__in=["closed", "cancelled", "rejected"])
        .distinct()
        .count()
    )
    closed_activities = acts.filter(status="closed").count()

    kpis = [
        {
            "label": "Total Projects",
            "value": str(len(project_ids)),
            "icon": "briefcase",
            "variant": "primary",
            "helper": "In your scope",
        },
        {
            "label": "Active Projects",
            "value": str(len(active_project_ids)),
            "icon": "chart",
            "variant": "primary",
            "helper": "With in-flight work",
        },
        {
            "label": "Project Schools",
            "value": str(len(school_ids)),
            "icon": "school",
            "variant": "info",
            "helper": "Assigned cohorts",
            "link": "/planning",
        },
        {
            "label": "Teachers Trained",
            "value": f"{teachers_trained:,}",
            "icon": "users",
            "variant": "info",
            "helper": "Verified trainings",
        },
        {
            "label": "Leaders Trained",
            "value": f"{leaders_trained:,}",
            "icon": "users",
            "variant": "info",
            "helper": "Verified trainings",
        },
        {
            "label": "Learners Reached",
            "value": f"{learners_reached:,}",
            "icon": "users",
            "variant": "success",
            "helper": "At schools visited",
        },
        {
            "label": "Assigned Partners",
            "value": str(partner_links.values("partner_id").distinct().count()),
            "icon": "briefcase",
            "variant": "analytics",
            "helper": "Delivery partners",
        },
        {
            "label": "Budget Generated",
            "value": _fmt_ugx(budget_generated),
            "icon": "finance",
            "variant": "success",
            "helper": "Auto from schedules",
            "link": "/weekly-fund-request",
        },
        {
            "label": "Activities in My Plan",
            "value": f"{activities_in_plan:,}",
            "icon": "calendar",
            "variant": "primary",
            "helper": "In the pipeline",
            "link": "/my-plan",
        },
        {
            "label": "Evidence Pending",
            "value": f"{evidence_pending:,}",
            "icon": "document",
            "variant": "warning",
            "helper": "Awaiting proof",
        },
        {
            "label": "IA Pending",
            "value": f"{ia_pending:,}",
            "icon": "shield",
            "variant": "warning",
            "helper": "Awaiting verification",
        },
        {
            "label": "Closed Activities",
            "value": f"{closed_activities:,}",
            "icon": "check",
            "variant": "success",
            "helper": "Fully cleared",
        },
    ]

    # ── Per-project portfolio + geography map ─────────────────────────────────
    schools_by_project: dict[str, int] = {}
    districts_by_project: dict[str, set] = {}
    regions_by_project: dict[str, set] = {}
    for a in psa:
        schools_by_project[a.project_id] = schools_by_project.get(a.project_id, 0) + 1
        if a.school and a.school.district_id:
            districts_by_project.setdefault(a.project_id, set()).add(
                a.school.district.name
            )
        if a.school and a.school.region_id:
            regions_by_project.setdefault(a.project_id, set()).add(a.school.region.name)

    partners_by_project: dict[str, list] = {}
    for link in partner_links:
        partners_by_project.setdefault(link.project_id, []).append(link.partner.name)

    budget_by_project = {
        row["activity__project_id"]: row["n"]
        for row in lines.values("activity__project_id").annotate(n=Sum("amount"))
    }
    act_counts: dict[str, dict[str, int]] = {}
    for row in acts.values("project_id", "status"):
        d = act_counts.setdefault(row["project_id"], {"total": 0, "closed": 0})
        d["total"] += 1
        if row["status"] == "closed":
            d["closed"] += 1

    cat_labels = dict(ProjectCategory.choices)
    portfolio = []
    for p in projects:
        counts = act_counts.get(p.id, {"total": 0, "closed": 0})
        completion = (
            round(counts["closed"] / counts["total"] * 100) if counts["total"] else 0
        )
        status_label, status_tone = _status_band(completion, counts["total"])
        districts = sorted(districts_by_project.get(p.id, set()))
        regions = sorted(regions_by_project.get(p.id, set()))
        prs = partners_by_project.get(p.id, [])
        portfolio.append(
            {
                "id": p.id,
                "name": p.name,
                "code": p.code or "",
                "type": cat_labels.get(p.category, p.category or "—"),
                "region": regions[0] if regions else "—",
                "district": (
                    districts[0]
                    if len(districts) == 1
                    else (f"{len(districts)} districts" if districts else "—")
                ),
                "schools": schools_by_project.get(p.id, 0),
                "partner": prs[0] if prs else "—",
                "partner_extra": max(0, len(prs) - 1),
                "budget": _fmt_ugx(budget_by_project.get(p.id, 0)),
                "completion": completion,
                "status": status_label,
                "status_tone": status_tone,
            }
        )

    # ── Selected project (right rail) ─────────────────────────────────────────
    selected = None
    sel = next(
        (p for p in projects if p.id == selected_project_id),
        projects[0] if projects else None,
    )
    if sel:
        counts = act_counts.get(sel.id, {"total": 0, "closed": 0})
        completion = (
            round(counts["closed"] / counts["total"] * 100) if counts["total"] else 0
        )
        status_label, status_tone = _status_band(completion, counts["total"])
        sel_school_ids = [a.school_id for a in psa if a.project_id == sel.id]
        no_ssa = School.objects.filter(
            id__in=sel_school_ids, current_fy_ssa_status="not_done"
        ).count()
        sel_acts = acts.filter(project_id=sel.id)
        start_dates = [
            a.start_date for a in psa if a.project_id == sel.id and a.start_date
        ]
        intervention_label = sel.get_intervention_display() if sel.intervention else "—"
        sel_delivered = sel_acts.filter(status__in=DELIVERED_STATUSES)
        selected = {
            "id": sel.id,
            "name": sel.name,
            "code": sel.code or "",
            "type": cat_labels.get(sel.category, sel.category or "—"),
            "coordinator": _coordinator_name(sel.manager_staff_id),
            "focus": intervention_label,
            "regions": ", ".join(sorted(regions_by_project.get(sel.id, set()))) or "—",
            "start_date": min(start_dates) if start_dates else None,
            "status": status_label,
            "status_tone": status_tone,
            "completion": completion,
            "attention": {
                "no_ssa": no_ssa,
                "partner_pending": sel_acts.filter(
                    status="assigned_to_partner"
                ).count(),
                "evidence_overdue": sel_acts.filter(
                    Q(status__in=["in_progress", "completion_started"])
                    | Q(evidence_status__in=["uploaded", "returned"])
                )
                .exclude(status__in=["closed", "cancelled", "rejected"])
                .distinct()
                .count(),
                "ia_returns": sel_acts.filter(
                    Q(status="returned_by_ia") | Q(ia_verification_status="flagged")
                ).count(),
            },
            "impact": {
                "schools_improved": sel_delivered.values("school_id")
                .distinct()
                .count(),
                "teachers_trained": sel_delivered.filter(
                    activity_type__in=TRAINING_TYPES
                ).aggregate(n=Sum("teachers_attended"))["n"]
                or 0,
                "learners_reached": School.objects.filter(
                    id__in=set(sel_delivered.values_list("school_id", flat=True))
                ).aggregate(n=Sum("enrollment"))["n"]
                or 0,
            },
            "next_step": (
                f"Schedule baseline SSA for {no_ssa} school{'s' if no_ssa != 1 else ''} "
                "without a current assessment."
                if no_ssa
                else "All project schools have a current SSA — schedule support activities."
            ),
            "next_step_cta": "Go to Planning",
            "next_step_href": "/planning",
        }

    # ── Project Planning Queue (real readiness from stored fields) ─────────────
    queue = []
    for a in psa:
        s = a.school
        if not s:
            continue
        ssa = s.current_fy_ssa_status
        readiness = s.planning_readiness
        if ssa == "not_done":
            state, tone, action, href = (
                "Baseline Required",
                "warning",
                "Schedule SSA",
                "/planning",
            )
        elif readiness == "in_my_plan":
            state, tone, action, href = (
                "In My Plan",
                "info",
                "View in My Plan",
                "/my-plan",
            )
        elif readiness == "ready_for_partner_assignment":
            state, tone, action, href = (
                "Partner Pending Schedule",
                "purple",
                "Assign to Partner",
                "/planning",
            )
        elif readiness == "scheduled":
            state, tone, action, href = (
                "Scheduled",
                "success",
                "View School",
                "/planning",
            )
        elif readiness == "requires_cluster":
            state, tone, action, href = (
                "Cluster Required",
                "neutral",
                "Add to Cluster",
                "/clusters",
            )
        else:
            state, tone, action, href = (
                "Ready for Support",
                "success",
                "Schedule Activity",
                "/planning",
            )
        queue.append(
            {
                "school": s.name,
                "school_id": s.school_id,
                "district": s.district.name if s.district_id else "—",
                "contact": s.primary_contact_name or s.headteacher_name or "—",
                "phone": s.primary_contact_phone or "",
                "state": state,
                "tone": tone,
                "action": action,
                "href": href,
            }
        )
    # Surface schools needing action first.
    queue.sort(key=lambda r: r["state"] in ("In My Plan", "Scheduled"))
    queue_total = len(queue)

    # ── Partner Assignment & Delivery ─────────────────────────────────────────
    partner_rows = []
    seen_partner = set()
    for link in partner_links:
        if link.partner_id in seen_partner:
            continue
        seen_partner.add(link.partner_id)
        pacts = acts.filter(assigned_partner_id=link.partner_id)
        p_total = pacts.count()
        p_closed = pacts.filter(status="closed").count()
        p_completion = round(p_closed / p_total * 100) if p_total else 0
        ev_ok = pacts.filter(evidence_status__in=["accepted"]).count()
        partner_rows.append(
            {
                "name": link.partner.name,
                "schools": pacts.values("school_id").distinct().count(),
                "scheduled": pacts.exclude(status__in=NOT_IN_PLAN_STATUSES).count(),
                "evidence": f"{ev_ok}/{p_total}" if p_total else "—",
                "ia_status": (
                    "On Track"
                    if p_completion >= 50
                    else ("Pending" if p_total else "—")
                ),
                "completion": p_completion,
            }
        )

    # ── Budget & Execution Summary ────────────────────────────────────────────
    def _bucket_sum(types):
        return (
            lines.filter(activity__activity_type__in=types).aggregate(n=Sum("amount"))[
                "n"
            ]
            or 0
        )

    total_budget = budget_generated
    disbursed = (
        lines.filter(
            activity__payment_status__in=[
                "accountant_cleared",
                "paid",
                "closed",
                "netsuite_accountability",
            ]
        ).aggregate(n=Sum("amount"))["n"]
        or 0
    )
    budget_summary = {
        "total": _fmt_ugx(total_budget),
        "buckets": [
            {"label": "Visits", "value": _fmt_ugx(_bucket_sum(VISIT_TYPES))},
            {"label": "Trainings", "value": _fmt_ugx(_bucket_sum(TRAINING_TYPES))},
            {"label": "SSA Collection", "value": _fmt_ugx(_bucket_sum(SSA_TYPES))},
            {
                "label": "Partner Activities",
                "value": _fmt_ugx(
                    _bucket_sum(["partner_activity", "project_activity"])
                ),
            },
        ],
        "utilization": round(disbursed / total_budget * 100) if total_budget else 0,
    }

    # ── Impact & Intervention Performance (real delivered counts by focus) ────
    from apps.core.enums import SsaIntervention

    focus_labels = dict(SsaIntervention.choices)
    by_focus: dict[str, dict[str, int]] = {}
    for row in delivered.values("focus_intervention", "delivery_type"):
        fi = row["focus_intervention"] or "unspecified"
        d = by_focus.setdefault(fi, {"staff": 0, "partner": 0})
        d[row["delivery_type"] or "staff"] += 1
    impact_bars = [
        {
            "label": focus_labels.get(fi, fi.replace("_", " ").title()),
            "staff": d["staff"],
            "partner": d["partner"],
            "total": d["staff"] + d["partner"],
        }
        for fi, d in sorted(
            by_focus.items(), key=lambda kv: -(kv[1]["staff"] + kv[1]["partner"])
        )[:6]
    ]
    impact_max = max((b["total"] for b in impact_bars), default=0)

    return {
        "kpis": kpis,
        "portfolio": portfolio,
        "selected": selected,
        "queue": queue[:6],
        "queue_total": queue_total,
        "partner_rows": partner_rows,
        "budget_summary": budget_summary,
        "impact_bars": impact_bars,
        "impact_max": impact_max,
        "has_projects": bool(project_ids),
        "is_country": scope.country_scope,
    }
