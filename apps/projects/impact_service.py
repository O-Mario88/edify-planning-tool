"""Special Project Impact Intelligence — real scoring & recommendation engine.

Computes, from verified engine data only (SSA `confirmed` records, IA-verified
activities, evidence, cost lines), the impact intelligence the spec requires:

  • Project SSA impact delta  = mean(latest_verified − earliest_verified SsaScore)
    across a project's supported schools × its attached interventions.
  • Project impact classification (Great / Positive / No / Negative / Not
    Measurable Yet / Insufficient Data) with data-quality safeguards.
  • Partner Impact Score (weighted) + partner classification (Scale Up / Keep
    Active / Under Review / Reduce / Drop / Insufficient Data).
  • Intervention impact, best/review/watchlist, recommendation counts, insights.

No fabricated numbers. Where the before/after evidence does not yet exist the
result is honestly "Not Measurable Yet" / "Insufficient Data" — never a guess.

Not yet modelled (shown as deferred, not faked): school-level ADOPTION indicators
(spec §5) need `ProjectAdoptionIndicator`/`Evidence` models. The partner score
therefore renormalises the spec's weights across the components we can verify.
"""

from __future__ import annotations

from django.db.models import Sum

from apps.core.enums import SsaIntervention
from apps.core.scoping import resolve_user_scope

from .dashboard_service import DELIVERED_STATUSES, _fmt_ugx
from .models import Project, ProjectPartnerAssignment, ProjectSchoolAssignment

INTERVENTION_LABELS = dict(SsaIntervention.choices)
INTERVENTION_ABBR = {
    "christlike_behaviour": "CB",
    "exposure_to_word_of_god": "WOG",
    "financial_health": "FH",
    "leadership": "Lship",
    "learning_environment": "LE",
    "government_requirement": "GR",
    "teaching_environment": "TE",
    "enrolment": "Erlm't",
}

# Data-quality floors — below these, we refuse to classify (spec §16).
MIN_MEASURABLE_SCHOOLS = 3
MIN_PARTNER_ACTIVITIES = 3

# Impact classification tones for the UI.
CLASS_TONE = {
    "Great Impact": "success",
    "Positive Impact": "success",
    "No Measurable Impact": "neutral",
    "Negative Impact": "danger",
    "Not Measurable Yet": "info",
    "Insufficient Data": "info",
}


def _collect_ssa_deltas(school_ids, interventions):
    """For the given schools × interventions, return baseline/latest/delta stats
    using ONLY IA-confirmed SSA records. A (school, intervention) pair is
    'measurable' only when it has ≥2 confirmed records (a before and an after)."""
    from apps.ssa.models import SsaScore

    if not school_ids or not interventions:
        return {
            "baseline_avg": None,
            "latest_avg": None,
            "delta": None,
            "measurable_pairs": 0,
            "improved_schools": set(),
            "declined_schools": set(),
        }
    rows = (
        SsaScore.objects.filter(
            ssa_record__school_id__in=list(school_ids),
            intervention__in=list(interventions),
            ssa_record__verification_status="confirmed",
            ssa_record__deleted_at__isnull=True,
        )
        .values_list(
            "ssa_record__school_id", "intervention", "score", "ssa_record__date_of_ssa"
        )
        .order_by("ssa_record__date_of_ssa")
    )
    acc: dict[tuple, list] = {}
    for sid, interv, score, _date in rows:
        acc.setdefault((sid, interv), []).append(score)

    baselines, latests, deltas = [], [], []
    improved, declined = set(), set()
    for (sid, _interv), scores in acc.items():
        if len(scores) >= 2:
            b, latest = scores[0], scores[-1]
            baselines.append(b)
            latests.append(latest)
            deltas.append(latest - b)
            if latest - b > 0.05:
                improved.add(sid)
            elif latest - b < -0.05:
                declined.add(sid)
    return {
        "baseline_avg": round(sum(baselines) / len(baselines), 1)
        if baselines
        else None,
        "latest_avg": round(sum(latests) / len(latests), 1) if latests else None,
        "delta": round(sum(deltas) / len(deltas), 2) if deltas else None,
        "measurable_pairs": len(deltas),
        "improved_schools": improved,
        "declined_schools": declined,
    }


def _classify_project(delta, target_achievement, measurable_schools):
    """Impact classification (spec §4) with a data-quality gate."""
    if measurable_schools == 0:
        return "Not Measurable Yet"
    if measurable_schools < MIN_MEASURABLE_SCHOOLS:
        return "Insufficient Data"
    if delta is None:
        return "Not Measurable Yet"
    if delta >= 1.5 and target_achievement >= 0.85:
        return "Great Impact"
    if delta >= 0.5:
        return "Positive Impact"
    if delta <= -0.5:
        return "Negative Impact"
    return "No Measurable Impact"


PROJECT_RECOMMENDATION = {
    "Great Impact": "Scale Project",
    "Positive Impact": "Continue Project",
    "No Measurable Impact": "Redesign Project",
    "Negative Impact": "Terminate / Review Project",
    "Not Measurable Yet": "Establish baseline & post-support SSA",
    "Insufficient Data": "Collect more verified SSA before judging",
}


def _clamp01(x):
    return max(0.0, min(1.0, x))


def _ssa_component(delta):
    """Map an SSA delta (roughly −1 … +1.5) to 0..1."""
    if delta is None:
        return 0.0
    return _clamp01((delta + 1.0) / 2.5)


def _partner_score(parts):
    """Weighted Partner Impact Score (spec §7), renormalised without adoption
    (adoption indicators are not modelled yet). Returns 0..100."""
    weights = {
        "ssa": 0.35,
        "target": 0.24,
        "ia": 0.12,
        "evidence": 0.12,
        "timeliness": 0.12,
        "cost": 0.05,
    }
    total = (
        weights["ssa"] * _ssa_component(parts["delta"])
        + weights["target"] * _clamp01(parts["target_achievement"])
        + weights["ia"] * _clamp01(parts["ia_rate"])
        + weights["evidence"] * _clamp01(parts["evidence_rate"])
        + weights["timeliness"] * _clamp01(parts["timeliness"])
        + weights["cost"] * _clamp01(parts["cost_discipline"])
    )
    return round(total * 100)


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


def get_analytics(principal, filters=None) -> dict:
    from apps.activities.models import Activity, ActivityScheduleCostLine

    scope = resolve_user_scope(principal)

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

    psa = ProjectSchoolAssignment.objects.filter(project_id__in=project_ids)
    acts = Activity.objects.filter(deleted_at__isnull=True, project_id__in=project_ids)
    lines = ActivityScheduleCostLine.objects.filter(
        activity__project_id__in=project_ids
    )

    schools_by_project: dict[str, list] = {}
    for a in psa.values("project_id", "school_id"):
        schools_by_project.setdefault(a["project_id"], []).append(a["school_id"])

    # Per-project activity rollup.
    proj_acts: dict[str, list] = {}
    for a in acts.values(
        "project_id",
        "school_id",
        "status",
        "focus_intervention",
        "delivery_type",
        "assigned_partner_id",
        "evidence_status",
        "ia_verification_status",
        "reschedule_count",
        "cost_missing",
    ):
        proj_acts.setdefault(a["project_id"], []).append(a)

    budget_by_project = {
        row["activity__project_id"]: row["n"]
        for row in lines.values("activity__project_id").annotate(n=Sum("amount"))
    }

    # ── Per-project impact rows (the Impact Matrix / classification source) ────
    matrix = []
    class_counts = {
        "Great Impact": 0,
        "Positive Impact": 0,
        "No Measurable Impact": 0,
        "Negative Impact": 0,
        "Not Measurable Yet": 0,
        "Insufficient Data": 0,
    }
    schools_improved_total, schools_declined_total = set(), set()
    intervention_stats: dict[str, dict] = {}

    for p in projects:
        p_acts = proj_acts.get(p.id, [])
        assigned_ids = set(schools_by_project.get(p.id, []))
        delivered = [a for a in p_acts if a["status"] in DELIVERED_STATUSES]
        supported_ids = {a["school_id"] for a in delivered if a["school_id"]}

        interventions = {p.intervention} if p.intervention else set()
        interventions |= {
            a["focus_intervention"] for a in p_acts if a["focus_intervention"]
        }
        interventions = {i for i in interventions if i}

        ssa = _collect_ssa_deltas(supported_ids, interventions)
        total_acts = len([a for a in p_acts if a["status"] != "not_planned"])
        target_achievement = (len(delivered) / total_acts) if total_acts else 0.0
        classification = _classify_project(
            ssa["delta"], target_achievement, ssa["measurable_pairs"]
        )
        class_counts[classification] += 1
        schools_improved_total |= ssa["improved_schools"]
        schools_declined_total |= ssa["declined_schools"]

        # accumulate intervention-level stats
        for interv in interventions:
            st = intervention_stats.setdefault(
                interv, {"projects": set(), "schools": set(), "deltas": []}
            )
            st["projects"].add(p.id)
            st["schools"] |= supported_ids
            if ssa["delta"] is not None:
                st["deltas"].append((ssa["delta"], p.name))

        matrix.append(
            {
                "id": p.id,
                "name": p.name,
                "interventions": ", ".join(
                    INTERVENTION_ABBR.get(i, i) for i in sorted(interventions)
                )
                or "—",
                "schools_assigned": len(assigned_ids),
                "schools_supported": len(supported_ids),
                "baseline_avg": ssa["baseline_avg"]
                if ssa["baseline_avg"] is not None
                else "—",
                "latest_avg": ssa["latest_avg"]
                if ssa["latest_avg"] is not None
                else "—",
                "delta": ssa["delta"],
                "target_achievement": round(target_achievement * 100),
                "budget": _fmt_ugx(budget_by_project.get(p.id, 0)),
                "classification": classification,
                "tone": CLASS_TONE.get(classification, "neutral"),
                "recommendation": PROJECT_RECOMMENDATION.get(classification, "—"),
            }
        )

    # ── Intervention impact table (spec §C) ───────────────────────────────────
    interventions_out = []
    for code, st in sorted(
        intervention_stats.items(),
        key=lambda kv: -(sum(d for d, _ in kv[1]["deltas"]) / len(kv[1]["deltas"]))
        if kv[1]["deltas"]
        else 0,
    ):
        deltas = st["deltas"]
        avg_delta = (
            round(sum(d for d, _ in deltas) / len(deltas), 2) if deltas else None
        )
        best = max(deltas, key=lambda d: d[0])[1] if deltas else "—"
        worst = min(deltas, key=lambda d: d[0])[1] if deltas else "—"
        interventions_out.append(
            {
                "label": INTERVENTION_LABELS.get(code, code),
                "abbr": INTERVENTION_ABBR.get(code, code),
                "projects": len(st["projects"]),
                "schools": len(st["schools"]),
                "delta": avg_delta,
                "best": best,
                "worst": worst,
                "tone": "success"
                if (avg_delta or 0) >= 0.5
                else ("danger" if (avg_delta or 0) <= -0.5 else "neutral"),
            }
        )

    # ── Partner performance (spec §D, §7, §8) ──────────────────────────────────
    partner_links = ProjectPartnerAssignment.objects.filter(
        project_id__in=project_ids
    ).select_related("partner")
    project_name_by_id = {p.id: p.name for p in projects}
    partner_rows = []
    rec_counts = {
        "Scale Up": 0,
        "Keep Active": 0,
        "Under Review": 0,
        "Drop / Do Not Renew": 0,
        "Insufficient Data": 0,
    }
    all_partner_acts = list(
        acts.exclude(assigned_partner_id__isnull=True)
        .exclude(assigned_partner_id="")
        .values(
            "assigned_partner_id",
            "status",
            "school_id",
            "focus_intervention",
            "evidence_status",
            "ia_verification_status",
            "reschedule_count",
            "cost_missing",
            "project_id",
        )
    )
    for link in {pl.partner_id: pl for pl in partner_links}.values():
        pid = link.partner_id
        p_acts = [a for a in all_partner_acts if a["assigned_partner_id"] == pid]
        if not p_acts:
            continue
        completed = [a for a in p_acts if a["status"] in DELIVERED_STATUSES]
        assigned_n = len([a for a in p_acts if a["status"] != "not_planned"])
        target_achievement = (len(completed) / assigned_n) if assigned_n else 0.0
        ev_ok = len([a for a in completed if a["evidence_status"] == "accepted"])
        evidence_rate = (ev_ok / len(completed)) if completed else 0.0
        ia_ok = len(
            [
                a
                for a in p_acts
                if a["ia_verification_status"] == "confirmed"
                or a["status"] == "ia_verified"
            ]
        )
        ia_submitted = len(
            [
                a
                for a in p_acts
                if a["status"] in DELIVERED_STATUSES
                or a["ia_verification_status"] != "pending"
            ]
        )
        ia_rate = (ia_ok / ia_submitted) if ia_submitted else 0.0
        on_time = len([a for a in completed if (a["reschedule_count"] or 0) == 0])
        timeliness = (on_time / len(completed)) if completed else 0.0
        cost_ok = len([a for a in p_acts if not a["cost_missing"]])
        cost_discipline = (cost_ok / len(p_acts)) if p_acts else 0.0

        supported_ids = {a["school_id"] for a in completed if a["school_id"]}
        interventions = {
            a["focus_intervention"] for a in p_acts if a["focus_intervention"]
        }
        ssa = _collect_ssa_deltas(supported_ids, interventions)

        score = _partner_score(
            {
                "delta": ssa["delta"],
                "target_achievement": target_achievement,
                "ia_rate": ia_rate,
                "evidence_rate": evidence_rate,
                "timeliness": timeliness,
                "cost_discipline": cost_discipline,
            }
        )
        classification, tone = _classify_partner(
            score, len(completed), ssa["measurable_pairs"]
        )
        rec_counts[classification] = rec_counts.get(classification, 0) + 1
        # cost per improved school
        p_budget = (
            lines.filter(activity__assigned_partner_id=pid).aggregate(n=Sum("amount"))[
                "n"
            ]
            or 0
        )
        improved = len(ssa["improved_schools"])
        primary_project = ""
        proj_ids_for_partner = {a["project_id"] for a in p_acts}
        if len(proj_ids_for_partner) == 1:
            primary_project = project_name_by_id.get(
                next(iter(proj_ids_for_partner)), ""
            )
        partner_rows.append(
            {
                "name": link.partner.name,
                "project": primary_project or f"{len(proj_ids_for_partner)} projects",
                "schools_assigned": len(
                    {a["school_id"] for a in p_acts if a["school_id"]}
                ),
                "completed": len(completed),
                "target_achievement": round(target_achievement * 100),
                "delta": ssa["delta"],
                "ia_rate": round(ia_rate * 100),
                "cost_per_improved": _fmt_ugx(round(p_budget / improved))
                if improved
                else "—",
                "score": score if classification != "Insufficient Data" else "—",
                "recommendation": classification,
                "tone": tone,
            }
        )
    partner_rows.sort(
        key=lambda r: (r["score"] if isinstance(r["score"], int) else -1), reverse=True
    )

    # ── Headline KPIs (spec §A) ────────────────────────────────────────────────
    total_verified_acts = acts.filter(status__in=DELIVERED_STATUSES).count()
    from apps.ssa.models import SsaRecord

    verified_ssa = SsaRecord.objects.filter(
        school_id__in=[s for ids in schools_by_project.values() for s in ids],
        verification_status="confirmed",
        deleted_at__isnull=True,
    ).count()
    completed_acts = acts.filter(status__in=DELIVERED_STATUSES)
    ev_complete = completed_acts.filter(evidence_status="accepted").count()
    evidence_completion = (
        round(ev_complete / completed_acts.count() * 100)
        if completed_acts.count()
        else 0
    )
    total_budget = sum(budget_by_project.values())
    cost_per_improved = (
        _fmt_ugx(round(total_budget / len(schools_improved_total)))
        if schools_improved_total
        else "—"
    )
    impact_ready = sum(
        1
        for m in matrix
        if m["classification"]
        in (
            "Great Impact",
            "Positive Impact",
            "No Measurable Impact",
            "Negative Impact",
        )
    )

    kpis = [
        {
            "label": "Total Projects",
            "value": str(len(project_ids)),
            "icon": "briefcase",
            "variant": "primary",
            "helper": "In scope",
        },
        {
            "label": "Great Impact",
            "value": str(class_counts["Great Impact"]),
            "icon": "chart",
            "variant": "success",
            "helper": "Ready to scale",
        },
        {
            "label": "Positive Impact",
            "value": str(class_counts["Positive Impact"]),
            "icon": "check",
            "variant": "success",
            "helper": "Continue",
        },
        {
            "label": "No Impact",
            "value": str(class_counts["No Measurable Impact"]),
            "icon": "warning",
            "variant": "warning",
            "helper": "Redesign",
        },
        {
            "label": "Negative Impact",
            "value": str(class_counts["Negative Impact"]),
            "icon": "danger",
            "variant": "danger",
            "helper": "Review / terminate",
        },
        {
            "label": "Not Measurable Yet",
            "value": str(
                class_counts["Not Measurable Yet"] + class_counts["Insufficient Data"]
            ),
            "icon": "clock",
            "variant": "info",
            "helper": "Awaiting SSA/IA",
        },
        {
            "label": "Schools Improved",
            "value": str(len(schools_improved_total)),
            "icon": "school",
            "variant": "success",
            "helper": "Verified SSA gain",
        },
        {
            "label": "Schools Declined",
            "value": str(len(schools_declined_total)),
            "icon": "school",
            "variant": "danger",
            "helper": "Verified SSA drop",
        },
        {
            "label": "Budget Used",
            "value": _fmt_ugx(total_budget),
            "icon": "finance",
            "variant": "success",
            "helper": "From cost catalogue",
        },
        {
            "label": "Cost / Improved School",
            "value": cost_per_improved,
            "icon": "finance",
            "variant": "analytics",
            "helper": "Efficiency",
        },
        {
            "label": "Verified Activities",
            "value": f"{total_verified_acts:,}",
            "icon": "shield",
            "variant": "info",
            "helper": "IA-confirmed",
        },
        {
            "label": "Impact-Ready Projects",
            "value": str(impact_ready),
            "icon": "document",
            "variant": "primary",
            "helper": "Have before/after",
        },
    ]

    best_projects = [
        m for m in matrix if m["classification"] in ("Great Impact", "Positive Impact")
    ][:5]
    under_review = [
        m
        for m in matrix
        if m["classification"] in ("No Measurable Impact", "Insufficient Data")
    ][:5]
    watchlist = [m for m in matrix if m["classification"] == "Negative Impact"][:5]

    # Insights (spec §10/§G).
    insights = []
    if class_counts["Great Impact"]:
        insights.append(
            {
                "tone": "success",
                "title": f"{class_counts['Great Impact']} project(s) have great impact and are ready to scale.",
                "detail": ", ".join(
                    m["name"] for m in matrix if m["classification"] == "Great Impact"
                ),
            }
        )
    if rec_counts.get("Under Review"):
        insights.append(
            {
                "tone": "warning",
                "title": f"{rec_counts['Under Review']} partner(s) should be put under review.",
                "detail": ", ".join(
                    r["name"]
                    for r in partner_rows
                    if r["recommendation"] == "Under Review"
                ),
            }
        )
    if class_counts["Negative Impact"]:
        insights.append(
            {
                "tone": "danger",
                "title": f"{class_counts['Negative Impact']} project(s) show negative impact.",
                "detail": ", ".join(
                    m["name"]
                    for m in matrix
                    if m["classification"] == "Negative Impact"
                ),
            }
        )
    if class_counts["Not Measurable Yet"] + class_counts["Insufficient Data"]:
        insights.append(
            {
                "tone": "info",
                "title": f"{class_counts['Not Measurable Yet'] + class_counts['Insufficient Data']} project(s) are not measurable yet.",
                "detail": "Confirm baseline and post-support SSA, then IA-verify.",
            }
        )

    # Template-friendly distributions (Django can't dot-access dict keys with spaces).
    _class_meta = [
        ("Great Impact", "bg-emerald-600"),
        ("Positive Impact", "bg-emerald-400"),
        ("No Measurable Impact", "bg-slate-300"),
        ("Negative Impact", "bg-rose-400"),
        ("Not Measurable Yet", "bg-blue-300"),
        ("Insufficient Data", "bg-blue-200"),
    ]
    _total = len(project_ids) or 1
    class_dist = [
        {
            "label": label,
            "value": class_counts[label],
            "color": color,
            "pct": round(class_counts[label] / _total * 100, 1),
        }
        for label, color in _class_meta
    ]
    rec_dist = [
        {"label": "Scale Up", "value": rec_counts["Scale Up"], "tone": "success"},
        {"label": "Keep Active", "value": rec_counts["Keep Active"], "tone": "success"},
        {
            "label": "Under Review",
            "value": rec_counts["Under Review"],
            "tone": "warning",
        },
        {
            "label": "Drop / Do Not Renew",
            "value": rec_counts["Drop / Do Not Renew"],
            "tone": "danger",
        },
        {
            "label": "Insufficient Data",
            "value": rec_counts["Insufficient Data"],
            "tone": "neutral",
        },
    ]

    return {
        "kpis": kpis,
        "class_dist": class_dist,
        "class_total": len(project_ids),
        "interventions": interventions_out,
        "partners": partner_rows,
        "matrix": matrix,
        "best_projects": best_projects,
        "under_review": under_review,
        "watchlist": watchlist,
        "rec_dist": rec_dist,
        "insights": insights,
        "data_quality": {
            "verified_activities": total_verified_acts,
            "verified_ssa": verified_ssa,
            "evidence_completion": evidence_completion,
            "impact_ready": impact_ready,
        },
        "has_projects": bool(project_ids),
    }
