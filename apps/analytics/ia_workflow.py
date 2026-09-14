"""Impact Assessment's Outcomes view: school change and the strength of its
evidence (IA review, owner, 2026-09-13).

The role description's third responsibility is to evaluate school progress:
change in student outcomes, discipleship engagement and learning. The view
used to count project enrolments only — 25 of 703 schools in scope — so the
portfolio's paired SSA evidence sat on other pages, and its tiles bypassed the
metric registry and showed 0 where nothing was measured. It now reads, in
order:

  1. School change across the portfolio. Every school in the reader's scope
     with confirmed SSAs in the chosen financial year and the year before
     (apps.analytics.impact_engine.improvement_frame, the same pairs Declining
     Schools and Contribution Analysis read), judged by the one definition of
     improved and declined (apps.ssa.change_rules). Per outcome area and SSA
     domain: schools measured, improved and declined as a share of those
     measured, the median change, and an evidence grade
     (apps.analytics.evidence_strength). A domain whose rule is "maintain a
     Strong score" counts maintained schools separately and keeps them out of
     the median change.
  2. Evidence beyond the SSA: student learning results, discipleship practice
     and reviewed change stories, and EdTech rollout
     (apps.impact.evidence_services). Only confirmed records count.
  3. Project cohorts: each special-project enrolment's own baseline and
     follow-up, with unique schools beside enrolments.

Missing evidence is never zero: a figure with nothing measured reads "Not
measured" through the registry (apps/core/metrics/ia_outcome_metrics.py).

The portfolio sections are computed only when the Outcomes view renders them:
`outcome_workspace` hands the template a lazy `progress` (the Collection and
Reports views and the CSV download read the enrolment rows and never pay for
the portfolio).
"""

from collections import Counter
from functools import cache
from statistics import median

from django.db.models import Q
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

PORTFOLIO_LIMITATION = (
    "Schools with a confirmed SSA in both years, compared on the same domains. "
    "SSA scores are the school's self-assessment, read as school-level proxies; a "
    "before-and-after change is description, not proof that a programme caused it."
)

#: Enrolment states whose measured change is movement in the expected
#: direction (improved) or its opposite (declined); "maintained strong" and
#: "no change" are measured but are neither, so they carry a neutral tone.
STATE_TONES = {
    "improved": "success",
    "declined": "danger",
    "maintained_strong": "neutral",
    "no_change": "neutral",
    "overdue": "danger",
    "baseline_missing": "warning",
    "evidence_review": "warning",
    "not_scheduled": "warning",
    "due": "warning",
    "upcoming": "info",
}

INTERVENTION_LABELS = dict(SsaIntervention.choices)


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
        "assignment_id": assignment.id,
        "school_id": assignment.school_id,
        "school": assignment.school.name,
        "owner_id": assignment.school.account_owner_id or "",
        "project_id": assignment.project_id,
        "project": assignment.project.name,
        "intervention_code": intervention,
        "intervention": INTERVENTION_LABELS.get(intervention, "Not mapped"),
        "state": state,
        "status": state.replace("_", " ").capitalize(),
        "tone": STATE_TONES.get(state, "neutral"),
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


def _share(part, whole):
    return round(100 * part / whole) if whole else None


def _median(values):
    values = [v for v in values if v is not None]
    return round(median(values), 2) if values else None


def _chosen_fy(query) -> tuple[str, list[str]]:
    """The financial year the portfolio compares with the year before: a valid
    ?fy=, else the operational year."""
    from apps.core.fy import fy_options, get_operational_fy

    options = fy_options()
    getter = query.get if hasattr(query, "get") else dict(query or {}).get
    chosen = str(getter("fy") or "").strip()
    # FY2025 has no year before it on the platform, so it is never compared.
    choices = [o for o in options if int(o) > int(options[0])]
    fy = chosen if chosen in choices else get_operational_fy()
    return fy, choices


def _cohort_domains(measured_rows) -> list[dict]:
    """Project enrolments per SSA domain: enrolments and unique schools
    measured, improved and declined as a share of measured, and the median
    change of the enrolments judged on movement. "Maintained strong" is a
    measured result but not a movement, so it stays out of the change; a
    domain below the evidence floor shows its counts and withholds the change.
    """
    from apps.analytics.evidence_strength import MIN_N

    domains = []
    for code, label in SsaIntervention.choices:
        pairs = [row for row in measured_rows if row["intervention_code"] == code]
        moved = [row for row in pairs if row["state"] != "maintained_strong"]
        schools = {row["school_id"] for row in pairs}
        improved = sum(1 for row in pairs if row["state"] == "improved")
        declined = sum(1 for row in pairs if row["state"] == "declined")
        domains.append(
            {
                "code": code,
                "name": label,
                "pairs": len(pairs),
                "schools": len(schools),
                "improved": improved,
                "improved_pct": _share(improved, len(pairs)),
                "declined": declined,
                "declined_pct": _share(declined, len(pairs)),
                "maintained": sum(
                    1 for row in pairs if row["state"] == "maintained_strong"
                ),
                "delta": _median(row["delta"] for row in moved)
                if len(schools) >= MIN_N
                else None,
                "withheld": 0 < len(schools) < MIN_N,
            }
        )
    return domains


def _baseline_details(assignments, rows) -> None:
    """Tell "a confirmed SSA exists but the baseline was not captured" apart
    from "there is no confirmed SSA to capture" (apps.projects.baselines), so
    IA is not sent into the field for an assessment that already exists."""
    from apps.projects import baselines

    missing_ids = {
        row["assignment_id"] for row in rows if row["state"] == "baseline_missing"
    }
    if not missing_ids:
        return
    states = baselines.baseline_states([a for a in assignments if a.id in missing_ids])
    for row in rows:
        state = states.get(row["assignment_id"])
        if state == baselines.NOT_CAPTURED:
            row["action"] = (
                "A confirmed SSA exists; its baseline is captured on the next refresh"
            )
            row["baseline_state"] = "not_captured"
        elif state == baselines.NO_INTERVENTION:
            row["action"] = "Name the SSA domain this enrolment measures"
            row["baseline_state"] = "no_intervention"
        elif state == baselines.NO_CONFIRMED_SSA:
            row["baseline_state"] = "no_confirmed_ssa"


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
    ordered = list(
        assignments.order_by("follow_up_due_on", "school__name", "project_id")
    )
    today = timezone.localdate()
    rows = [evidence_row(row, today) for row in ordered]
    _baseline_details(ordered, rows)
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
    fy, fy_choices = _chosen_fy(query)

    @cache
    def progress():
        return outcome_progress(user, fy=fy)

    workspace = {
        "rows": rows,
        "projects": projects,
        "project": project,
        "total": len(rows),
        "unique_schools": len({row["school_id"] for row in rows}),
        "measured": len(measured),
        "measured_schools": len({row["school_id"] for row in measured}),
        "unmeasured": len(rows) - len(measured),
        "improved": counts["improved"],
        "declined": counts["declined"],
        "maintained": counts["maintained_strong"],
        "no_change": counts["no_change"],
        "baseline_missing": counts["baseline_missing"],
        "overdue": counts["overdue"],
        "due": counts["due"],
        "not_scheduled": counts["not_scheduled"],
        "domains": _cohort_domains(measured),
        "limitation": LIMITATION,
        "generated_at": timezone.now().isoformat(),
        "scope_label": scope.country or "Assigned access scope",
        "period": "All recorded project enrolments; each uses its own assessment window",
        "fy": fy,
        "fy_options": fy_choices,
        # Evaluated by the template only where the Outcomes view renders it.
        "progress": progress,
    }
    workspace["cohort_tiles"] = cohort_tiles(workspace)
    return workspace


# ── School change across the portfolio ──────────────────────────────────────


def _outcome_area_groups() -> list[dict]:
    """The approved outcome areas with their SSA domains (the newest approved
    version of each code), then every domain no approved area claims — one
    query. Areas are IA's to define and review (apps.impact.framework); none
    is assumed."""
    from apps.impact.models import DefinitionStatus, OutcomeAreaDomain

    areas: dict[str, dict] = {}
    for link in (
        OutcomeAreaDomain.objects.filter(area__status=DefinitionStatus.APPROVED)
        .select_related("area")
        .order_by("area__code", "-area__version", "intervention")
    ):
        area = link.area
        entry = areas.get(area.code)
        if entry is None:
            entry = areas[area.code] = {
                "code": area.code,
                "name": area.name,
                "version": area.version,
                "domains": [],
            }
        if (
            area.version == entry["version"]
            and link.intervention not in entry["domains"]
        ):
            entry["domains"].append(link.intervention)
    groups = sorted(areas.values(), key=lambda a: a["name"].lower())
    claimed = {code for group in groups for code in group["domains"]}
    unclaimed = [code for code in SsaIntervention.values if code not in claimed]
    if unclaimed:
        groups.append(
            {
                "code": "",
                "name": "Not yet in an approved outcome area",
                "version": None,
                "domains": unclaimed,
            }
        )
    return groups


def _change_row(name, pairs, verdicts, *, schools_in_scope, is_area):
    """One table row: schools measured, improved/declined shares of measured,
    median change of the pairs judged on movement, and the evidence grade."""
    from apps.analytics.evidence_strength import MIN_N, grade
    from apps.ssa import change_rules

    if is_area:
        results = list(verdicts.values())
        deltas = [
            v["mean_delta"]
            for v in results
            if v["classification"] != change_rules.MAINTAINED_STRONG
        ]
    else:
        results = pairs
        deltas = [
            p["delta"]
            for p in pairs
            if p["classification"] != change_rules.MAINTAINED_STRONG
        ]
    n = len(results)
    by_class = Counter(r["classification"] for r in results)
    evidence = grade(
        n,
        confirmed_share=1.0,
        missing_share=(1 - n / schools_in_scope) if schools_in_scope else None,
    )
    return {
        "name": name,
        "is_area": is_area,
        "n": n,
        "improved": by_class[change_rules.IMPROVED],
        "improved_pct": _share(by_class[change_rules.IMPROVED], n),
        "declined": by_class[change_rules.DECLINED],
        "declined_pct": _share(by_class[change_rules.DECLINED], n),
        "no_change": by_class[change_rules.NO_CHANGE],
        "maintained": by_class[change_rules.MAINTAINED_STRONG],
        "median_change": _median(deltas) if n >= MIN_N else None,
        "withheld": 0 < n < MIN_N,
        "grade": evidence,
        "rule_label": (pairs[0]["rule_label"] if pairs and not is_area else ""),
    }


def portfolio_change(user, *, fy: str) -> dict:
    """Paired confirmed SSAs across every school in the reader's scope, FY-1
    against FY, judged by apps.ssa.change_rules (seven queries at most)."""
    from apps.analytics.evidence_strength import grade
    from apps.analytics.impact_engine import improvement_frame
    from apps.ssa import change_rules

    scope = resolve_user_scope(user)
    schools = scoped_school_queryset(scope)
    prev_fy = str(int(fy) - 1)
    base = {
        "fy": fy,
        "prev_fy": prev_fy,
        "schools_in_scope": 0,
        "measured": 0,
        "improved": 0,
        "declined": 0,
        "no_change": 0,
        "improved_pct": None,
        "declined_pct": None,
        "median_interval_days": None,
        "rows": [],
        "rule_label": change_rules.FALLBACK_LABEL,
        "rule_sentence": change_rules.RULE_SENTENCE,
        "grade": grade(0),
        "limitation": PORTFOLIO_LIMITATION,
    }
    if schools is None or scope.can_view_summary_only:
        return base
    countries = dict(schools.values_list("id", "region__country"))
    base["schools_in_scope"] = len(countries)
    if not countries:
        return base
    frame = improvement_frame(list(countries), fy)
    book = change_rules.RuleBook()
    base["rule_label"] = change_rules.rule_label_for(book)

    def country_for(school_id):
        return countries.get(school_id) or ""

    pairs = (
        change_rules.classify_pairs(
            frame.to_dict("records"), book=book, country_for=country_for
        )
        if not frame.empty
        else []
    )
    groups = _outcome_area_groups()
    if not pairs:
        base["rows"] = [
            {"name": g["name"], "is_area": True, "n": 0, "domains": g["domains"]}
            for g in groups
        ]
        return base
    verdicts = change_rules.school_verdicts(pairs, book=book, country_for=country_for)
    by_class = Counter(v["classification"] for v in verdicts.values())
    intervals = {
        p["school_id"]: (p["window_end"] - p["window_start"]).days
        for p in pairs
        if p.get("window_start") and p.get("window_end")
    }
    measured = len(verdicts)
    base.update(
        measured=measured,
        improved=by_class[change_rules.IMPROVED],
        declined=by_class[change_rules.DECLINED],
        no_change=by_class[change_rules.NO_CHANGE],
        improved_pct=_share(by_class[change_rules.IMPROVED], measured),
        declined_pct=_share(by_class[change_rules.DECLINED], measured),
        median_interval_days=round(median(intervals.values())) if intervals else None,
        grade=grade(
            measured,
            confirmed_share=1.0,
            missing_share=1 - measured / len(countries),
        ),
    )

    rows = []
    for group in groups:
        area_pairs = [p for p in pairs if p["intervention"] in group["domains"]]
        area_verdicts = change_rules.school_verdicts(
            area_pairs, book=book, country_for=country_for
        )
        rows.append(
            {
                **_change_row(
                    group["name"],
                    area_pairs,
                    area_verdicts,
                    schools_in_scope=len(countries),
                    is_area=True,
                ),
                "domains": group["domains"],
            }
        )
        for code in group["domains"]:
            domain_pairs = [p for p in area_pairs if p["intervention"] == code]
            rows.append(
                _change_row(
                    INTERVENTION_LABELS.get(code, code),
                    domain_pairs,
                    {},
                    schools_in_scope=len(countries),
                    is_area=False,
                )
            )
    base["rows"] = rows
    return base


def outcome_progress(user, *, fy: str) -> dict:
    """Everything the Outcomes view reads above the project cohorts: the
    portfolio's school change and the evidence beyond the SSA."""
    from apps.impact.evidence_services import outcome_evidence

    portfolio = portfolio_change(user, fy=fy)
    evidence = outcome_evidence(user, fy)
    return {
        "portfolio": portfolio,
        "evidence": evidence,
        "tiles": portfolio_tiles(portfolio),
    }


def _metric(label, value, helper, tone="info", **extra):
    from apps.core.metrics import render_precomputed_metric_for_source

    return render_precomputed_metric_for_source(
        "apps.analytics.ia_workflow:_metric",
        label,
        value,
        helper=helper,
        tone=tone,
        **extra,
    )


def portfolio_tiles(portfolio: dict) -> list[dict]:
    """The Outcomes view's school-change tiles, through the reconciled
    registry. Nothing measured reads "Not measured", never 0."""
    measured = portfolio["measured"]
    period = f"FY{portfolio['prev_fy']} → FY{portfolio['fy']}"
    return [
        _metric(
            "Schools With Paired Confirmed SSAs",
            f"{measured} / {portfolio['schools_in_scope']}",
            f"{period}, readings at least 120 days apart",
            raw_value=measured,
        ),
        _metric(
            "Schools Improved (Share of Measured)",
            f"{portfolio['improved_pct']}%" if measured else "Not measured",
            f"{portfolio['improved']} of {measured} schools · {portfolio['rule_label']}"
            if measured
            else "no school has two comparable confirmed SSAs",
            "success" if measured else "neutral",
            raw_value=portfolio["improved_pct"],
        ),
        _metric(
            "Schools Declined (Share of Measured)",
            f"{portfolio['declined_pct']}%" if measured else "Not measured",
            f"{portfolio['declined']} of {measured} schools · {portfolio['rule_label']}"
            if measured
            else "no school has two comparable confirmed SSAs",
            "danger" if measured and portfolio["declined"] else "neutral",
            raw_value=portfolio["declined_pct"],
        ),
        _metric(
            "Median Days Between Paired SSAs",
            portfolio["median_interval_days"] if measured else "Not measured",
            "between the two confirmed readings compared",
            "neutral",
            raw_value=portfolio["median_interval_days"],
        ),
    ]


def cohort_tiles(workspace: dict) -> list[dict]:
    """The project cohort tiles (Outcomes and Reports views)."""
    measured = workspace["measured"]
    total = workspace["total"]
    project = workspace.get("project") or ""
    suffix = f"&project={project}" if project else ""
    return [
        _metric(
            "Project Enrolments Measured",
            f"{measured} / {total}",
            f"{workspace['measured_schools']} of {workspace['unique_schools']} unique schools",
            raw_value=measured,
        ),
        _metric(
            "Project Enrolments Improved",
            f"{_share(workspace['improved'], measured)}%"
            if measured
            else "Not measured",
            f"{workspace['improved']} of {measured} measured enrolments"
            if measured
            else "no enrolment has a confirmed baseline and follow-up",
            "success" if measured else "neutral",
            raw_value=_share(workspace["improved"], measured),
        ),
        _metric(
            "Project Enrolments Declined",
            f"{_share(workspace['declined'], measured)}%"
            if measured
            else "Not measured",
            f"{workspace['declined']} of {measured} measured enrolments"
            if measured
            else "no enrolment has a confirmed baseline and follow-up",
            "danger" if measured and workspace["declined"] else "neutral",
            raw_value=_share(workspace["declined"], measured),
        ),
        _metric(
            "Project Enrolments Missing a Baseline",
            workspace["baseline_missing"],
            "no confirmed baseline captured",
            "warning" if workspace["baseline_missing"] else "info",
            drilldown_url=f"/ia/dashboard/?view=collection{suffix}",
        ),
        _metric(
            "Project Follow-ups Overdue",
            workspace["overdue"],
            "past the follow-up window",
            "danger" if workspace["overdue"] else "info",
            drilldown_url=f"/ia/dashboard/?view=collection{suffix}",
        ),
    ]


# ── One school's progress (the school profile) ──────────────────────────────

#: Activity statuses Impact Assessment has verified (or later): the support a
#: school received between two readings is counted from these only.
VERIFIED_ACTIVITY_STATUSES = (
    "ia_verified",
    "accountant_confirmed",
    "completed",
    "closed",
)

#: How many before-and-after pairs the profile lists, newest first.
SCHOOL_PAIRS_SHOWN = 4


def school_progress(school) -> dict:
    """The school profile's SSA panel (IA review, owner, 2026-09-13).

    The headline is the newest CONFIRMED SSA (the platform's one "latest SSA"
    rule, apps.ssa.services.latest_applicable_record); a newer record still
    waiting for verification is named beside it and counted nowhere. The
    history lists every record with its verification status. Change is read
    between confirmed assessments of consecutive financial years — the pairs
    Declining Schools and the Outcomes view use — judged by apps.ssa.change_rules,
    each pair listing the verified activities delivered between the two
    readings. It counts the school once per pair, never once per activity.
    Four queries whatever the school's history.
    """
    from apps.activities.models import Activity
    from apps.ssa import change_rules
    from apps.ssa.models import SsaRecord, SsaScore

    records = list(
        SsaRecord.objects.filter(school=school, deleted_at__isnull=True).order_by(
            "-date_of_ssa", "-created_at"
        )
    )
    confirmed = [r for r in records if r.verification_status == "confirmed"]
    latest = confirmed[0] if confirmed else None
    newer_unconfirmed = [
        r
        for r in records
        if r.verification_status != "confirmed"
        and (latest is None or r.date_of_ssa > latest.date_of_ssa)
    ]

    # The latest confirmed record per financial year, newest year first.
    by_fy: dict[str, object] = {}
    for record in confirmed:
        by_fy.setdefault(record.fy, record)
    years = sorted(
        by_fy, key=lambda fy: int(fy) if str(fy).isdigit() else 0, reverse=True
    )
    pair_records = []
    for newer_fy in years:
        older_fy = str(int(newer_fy) - 1) if str(newer_fy).isdigit() else ""
        if older_fy in by_fy:
            pair_records.append((by_fy[older_fy], by_fy[newer_fy]))
        if len(pair_records) >= SCHOOL_PAIRS_SHOWN:
            break

    wanted = {r.id for pair in pair_records for r in pair}
    if latest is not None:
        wanted.add(latest.id)
    scores: dict[str, dict[str, float]] = {}
    for row in SsaScore.objects.filter(ssa_record_id__in=wanted).values(
        "ssa_record_id", "intervention", "score"
    ):
        scores.setdefault(row["ssa_record_id"], {})[row["intervention"]] = float(
            row["score"]
        )

    country = school_country_of(school)
    book = change_rules.RuleBook() if pair_records else None
    windows = [
        (before.date_of_ssa.date(), after.date_of_ssa.date())
        for before, after in pair_records
    ]
    support: dict[int, list] = {i: [] for i in range(len(windows))}
    if windows:
        earliest = min(start for start, _end in windows)
        latest_end = max(end for _start, end in windows)
        delivered_support = (
            Activity.objects.filter(
                school=school,
                deleted_at__isnull=True,
                status__in=VERIFIED_ACTIVITY_STATUSES,
            )
            .filter(
                Q(actual_delivery_date__gte=earliest)
                | Q(actual_delivery_date__isnull=True, planned_date__gte=earliest)
            )
            .only(
                "id",
                "activity_type",
                "activity_name_snapshot",
                "actual_delivery_date",
                "planned_date",
            )
        )
        for activity in delivered_support:
            delivered = activity.actual_delivery_date or activity.planned_date
            if delivered is None or delivered > latest_end:
                continue
            for index, (start, end) in enumerate(windows):
                if start < delivered <= end:
                    support[index].append(activity)

    pairs = []
    for index, (before, after) in enumerate(pair_records):
        rows = [
            {
                "school_id": school.id,
                "intervention": code,
                "prev_score": scores.get(before.id, {}).get(code),
                "curr_score": scores.get(after.id, {}).get(code),
                "window_start": before.date_of_ssa.date(),
                "window_end": after.date_of_ssa.date(),
            }
            for code in SsaIntervention.values
            if code in scores.get(before.id, {}) and code in scores.get(after.id, {})
        ]
        judged = change_rules.classify_pairs(
            rows, book=book, country_for=lambda _s: country
        )
        verdict = change_rules.school_verdicts(
            judged, book=book, country_for=lambda _s: country
        ).get(school.id)
        activities = support[index]
        pairs.append(
            {
                "before": before,
                "after": after,
                "interval_days": (after.date_of_ssa - before.date_of_ssa).days,
                "comparable": bool(judged),
                "classification": verdict["classification"] if verdict else "",
                "classification_label": (
                    verdict["classification"].replace("_", " ").capitalize()
                    if verdict
                    else f"Not compared (readings less than {change_rules.MIN_INTERVAL_DAYS} days apart)"
                ),
                "tone": STATE_TONES.get(verdict["classification"], "neutral")
                if verdict
                else "neutral",
                "mean_delta": verdict["mean_delta"] if verdict else None,
                "rule_label": verdict["rule_label"] if verdict else "",
                "domains": [
                    {
                        "name": INTERVENTION_LABELS.get(
                            p["intervention"], p["intervention"]
                        ),
                        "before": p["prev_score"],
                        "after": p["curr_score"],
                        "delta": p["delta"],
                        "classification": p["classification"]
                        .replace("_", " ")
                        .capitalize(),
                        "tone": STATE_TONES.get(p["classification"], "neutral"),
                    }
                    for p in judged
                ],
                "support_count": len(activities),
                "support": [
                    (a.activity_name_snapshot or a.activity_type or "").replace(
                        "_", " "
                    )
                    for a in activities[:6]
                ],
            }
        )

    by_class = Counter(p["classification"] for p in pairs if p["classification"])
    progress_by_fy = []
    for fy in sorted(by_fy, key=lambda v: int(v) if str(v).isdigit() else 0):
        average = by_fy[fy].average_score
        progress_by_fy.append(
            {"fy": fy, "avg_score": float(average) if average is not None else None}
        )
    return {
        "latest": latest,
        "latest_scores": sorted(
            (
                {"label": INTERVENTION_LABELS.get(code, code), "score": score}
                for code, score in scores.get(latest.id, {}).items()
            ),
            key=lambda row: -row["score"],
        )
        if latest
        else [],
        "newer_unconfirmed": newer_unconfirmed,
        "history": [
            {
                "record": r,
                "status_label": r.get_verification_status_display(),
                "tone": {
                    "confirmed": "success",
                    "pending": "warning",
                    "returned": "danger",
                }.get(r.verification_status, "neutral"),
                "counted": r.verification_status == "confirmed",
            }
            for r in records
        ],
        "pairs": pairs,
        "improved_pairs": by_class.get("improved", 0),
        "declined_pairs": by_class.get("declined", 0),
        "progress_by_fy": progress_by_fy,
    }


def school_country_of(school) -> str:
    region = getattr(school, "region", None)
    return (getattr(region, "country", "") or "").strip()
