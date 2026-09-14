"""Programme Learning: what works across training, lending, EdTech and visits
(IA review, owner, 2026-09-13).

The role description asks Impact Assessment to "analyse qualitative and
quantitative data to distinguish what works" and to evaluate Christian
training, educational technology rollout and lending. The pieces were spread
over five pages that disagreed (/impact, the attribution page, Visit
Effectiveness, the lending reports and a dashboard tab of links), and no
surface showed delivery, outcome, comparison, sample size, missingness and
qualitative evidence together, or kept a conclusion.

Every tab of /ia/learning/ has the same four parts:

  1. Outputs, labelled "delivery, not impact" — what was done (registry tiles).
  2. An outcome table. For each programme group: the schools exposed and
     measured, the comparison schools, coverage (measured of reached) and the
     missing share, the period, the design, the median SSA change of each
     group, the difference, the Holm-corrected verdict and the shared evidence
     grade (apps.analytics.evidence_strength). One design everywhere:
       - pairs: confirmed SSAs in FY-1 and FY (impact_engine.improvement_frame),
         taken at least change_rules.MIN_INTERVAL_DAYS apart;
       - exposure: IA-verified work (or a disbursed loan, or a confirmed
         deployment) dated inside the school's own window between the two
         readings;
       - stratum: schools that started weak (below impact_engine.WEAK_BASELINE)
         on the outcome domain, because planning targets weakness and a
         comparison with strong schools only measures regression to the mean;
       - comparison: schools in the same stratum with no exposure of that
         kind on that domain at all.
     A group below MIN_GROUP_N on either side says "insufficient data".
  3. A qualitative panel: coded field challenges (debrief challenge types),
     the latest visit feedback, and — for training — the Regional Lead's
     shared observation rubric, reported as delivery QUALITY, never as outcome.
  4. "Record finding": an ImpactFinding (apps.impact.findings) that a
     different person reviews, carrying a snapshot of the row it came from.

Scope: the reader's analytics scope (apps.core.scoping.scoped_school_queryset)
— IA and the Country Director their country, Admin the deployment; a
summary-only reader sees no rows. Every filter a tab draws reaches the table
it filters; a filter with nothing to choose is not drawn.

Permanent caveats: association only, never proof; the SSA is the school's
self-assessment; for EdTech there is no learner-level digital-skill result,
so the Learning Environment domain is a school-level proxy.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import mean, median

import pandas as pd
from django.db.models import Count, Exists, OuterRef, Q

from apps.analytics import evidence_strength as es
from apps.core.activity_types import TRAINING_TYPES
from apps.core.enums import ActivityType, ProgrammeDeliveryMode, SsaIntervention
from apps.core.metrics import percentage

TRAINING = "training"
LENDING = "lending"
EDTECH = "edtech"
VISITS = "visits"
FINDINGS = "findings"

TABS = (
    (TRAINING, "Training"),
    (LENDING, "Lending"),
    (EDTECH, "EdTech"),
    (VISITS, "Visits"),
    (FINDINGS, "Findings"),
)
TAB_LABELS = dict(TABS)

#: The governed catalogue category that names EdTech programme work
#: (activity_catalogue seed data: EdTech Foundations, EdTech Integration,
#: Students Digital Skills Training). Matched exactly, never by a literal
#: typed elsewhere.
EDTECH_PROGRAMME_CATEGORY = "EdTech"
#: The EdTech special project.
EDTECH_PROJECT_CODE = "SP-EDTECH"

OUTPUTS_NOTE = "Delivery, not impact: these count what was done, not what changed."
ASSOCIATION_CAVEAT = (
    "Association, not proof: schools were not randomly chosen for the programme, "
    "so a difference may reflect which schools took part. The SSA is each "
    "school's own assessment."
)
EDTECH_CAVEAT = (
    "No learner-level digital-skill or learning result is captured for EdTech. "
    "The outcome is the SSA Learning Environment domain, a school-level proxy, "
    "read beside Impact Assessment's deployment checks (units working, teachers "
    "and learners using them)."
)
LENDING_CAVEAT = (
    "A loan takes time to change a school: exposures closer to the follow-up "
    "assessment than the purpose's follow-up window are flagged immature. "
    "Financial Health and Enrolment are self-assessed SSA domains."
)
OBSERVATION_NOTE = (
    "The Regional Lead's observation rubric describes how well a training was "
    "delivered. It is delivery quality, not an outcome."
)

DELIVERY_MODE_LABELS = {
    **{value: str(label) for value, label in ProgrammeDeliveryMode.choices},
    "cluster": "Cluster",
    "in_school": "In-school",
    "other": "Other delivery",
}
INTERVENTION_LABELS = {value: str(label) for value, label in SsaIntervention.choices}
ACTIVITY_TYPE_LABELS = {value: str(label) for value, label in ActivityType.choices}

LEARNING_ENVIRONMENT = SsaIntervention.LEARNING_ENVIRONMENT.value
LENDING_DOMAINS = (
    SsaIntervention.FINANCIAL_HEALTH.value,
    SsaIntervention.ENROLMENT.value,
)

#: Rows shown per page of an outcome table.
PAGE_SIZE = 25


# ── The population ──────────────────────────────────────────────────────────


@dataclass
class Population:
    """The reader's schools, their comparable SSA pairs and the IA-verified
    work inside each pair's window — built once per request."""

    fy: str
    prev_fy: str
    countries: dict
    imp: pd.DataFrame
    acts: pd.DataFrame
    too_close: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def school_ids(self) -> list[str]:
        return list(self.countries)

    @property
    def schools_in_scope(self) -> int:
        return len(self.countries)

    @property
    def paired(self) -> int:
        return int(self.imp["school_id"].nunique()) if not self.imp.empty else 0

    @property
    def period(self) -> str:
        return f"FY{self.prev_fy} → FY{self.fy}"


def fy_choices() -> list[str]:
    from apps.core.fy import fy_options

    return sorted(fy_options(), key=int, reverse=True)


def resolve_fy(value) -> str:
    from apps.core.fy import get_operational_fy

    value = str(value or "").strip()
    return value if value in fy_choices() else get_operational_fy()


def scoped_countries(principal) -> dict:
    """School id → country for every school the reader may analyse."""
    from apps.core.scoping import resolve_user_scope, scoped_school_queryset

    scope = resolve_user_scope(principal)
    if scope.can_view_summary_only:
        return {}
    schools = scoped_school_queryset(scope)
    if schools is None:
        return {}
    return dict(schools.values_list("id", "region__country"))


def population(principal, fy: str) -> Population:
    """Six queries at most, whatever the portfolio size (the SSA records and
    scores, the activities, their projects, spend and enrolments)."""
    from apps.analytics.impact_engine import activity_frame, improvement_frame
    from apps.ssa.change_rules import comparable

    countries = scoped_countries(principal)
    imp = improvement_frame(list(countries), fy)
    too_close = 0
    if not imp.empty:
        keep = [
            comparable(start, end)
            for start, end in zip(imp["window_start"], imp["window_end"])
        ]
        too_close = int(imp.loc[[not k for k in keep], "school_id"].nunique())
        imp = imp[keep].reset_index(drop=True)
    acts = activity_frame(imp, list(countries))
    return Population(
        fy=fy,
        prev_fy=str(int(fy) - 1),
        countries=countries,
        imp=imp,
        acts=acts,
        too_close=too_close,
    )


def _windows(imp: pd.DataFrame) -> dict:
    if imp.empty:
        return {}
    return (
        imp.groupby("school_id")[["window_start", "window_end"]]
        .first()
        .to_dict("index")
    )


def _in_window(windows: dict, school_id, day) -> bool:
    w = windows.get(school_id)
    return bool(w and day and w["window_start"] < day <= w["window_end"])


# ── One comparison row ──────────────────────────────────────────────────────


def compare(
    imp: pd.DataFrame,
    *,
    key: str,
    label: str,
    interventions,
    exposed_pairs: set,
    any_exposed_pairs: set,
    reached: int | None = None,
    flags=(),
    detail: str = "",
) -> dict:
    """Exposed against comparison schools in the weak-baseline stratum.

    `exposed_pairs` are the (school, intervention) pairs this group reached;
    `any_exposed_pairs` every pair reached by work of the same kind, which the
    comparison group must not contain. A school's outcome is the mean change
    across its eligible domains. `reached` is how many schools the group
    reached at all (measured or not), for coverage."""
    from apps.analytics.impact_engine import WEAK_BASELINE, _mann_whitney

    interventions = sorted(set(interventions))
    exposed: dict[str, list[float]] = defaultdict(list)
    comparison: dict[str, list[float]] = defaultdict(list)
    if not imp.empty and interventions:
        stratum = imp[
            imp["intervention"].isin(interventions)
            & (imp["prev_score"] < WEAK_BASELINE)
        ]
        for school_id, intervention, delta in zip(
            stratum["school_id"], stratum["intervention"], stratum["delta"]
        ):
            pair = (school_id, intervention)
            if pair in exposed_pairs:
                exposed[school_id].append(float(delta))
            elif pair not in any_exposed_pairs:
                comparison[school_id].append(float(delta))
    for school_id in exposed:
        comparison.pop(school_id, None)
    exposed_values = pd.Series([mean(v) for v in exposed.values()], dtype=float)
    comparison_values = pd.Series([mean(v) for v in comparison.values()], dtype=float)
    stats = _mann_whitney(exposed_values, comparison_values)
    exposed_n, comparison_n = len(exposed), len(comparison)
    reached = reached if reached is not None else None
    missing_share = max(0.0, 1 - exposed_n / reached) if reached else None
    return {
        "key": key,
        "label": label,
        "detail": detail,
        "outcome": ", ".join(INTERVENTION_LABELS.get(i, i) for i in interventions),
        "exposed_n": exposed_n,
        "comparison_n": comparison_n,
        "reached": reached,
        "coverage_pct": percentage(min(exposed_n, reached), reached)
        if reached
        else None,
        "missing_pct": round(missing_share * 100)
        if missing_share is not None
        else None,
        "median_exposed": stats["median_treated"],
        "median_comparison": stats["median_untreated"],
        "difference": stats["effect"],
        "p": stats["p"],
        "verdict": stats["verdict"],
        "_missing_share": missing_share,
        "_flags": tuple(flags),
    }


def finish_rows(
    rows: list[dict], *, period: str, design: str, caveat: str
) -> list[dict]:
    """One family: Holm-correct the rows, grade each, and label the design."""
    from apps.analytics.impact_engine import apply_holm

    apply_holm(rows)
    for row in rows:
        graded = es.grade(
            row["exposed_n"],
            n_comparison=row["comparison_n"],
            confirmed_share=1.0,
            missing_share=row.pop("_missing_share", None),
            design=es.STRATIFIED_COMPARISON,
            flags=row.pop("_flags", ()),
        )
        row.update(
            {
                "period": period,
                "design": design,
                "grade": graded["grade"],
                "grade_label": graded["label"],
                "grade_reasons": graded["reasons"],
                "grade_tone": es.grade_tone(graded["grade"]),
                "caveat": caveat,
            }
        )
    return rows


COMPARISON_DESIGN = "Weak-baseline schools: exposed against not exposed"


# ── Qualitative evidence ────────────────────────────────────────────────────


def _themes(activity_ids) -> list[dict]:
    """Coded field challenges from debriefs linked to the activities, most
    frequent first — the only coded qualitative data the platform holds."""
    from apps.debriefs.models import DailyDebriefChallenge

    activity_ids = list(activity_ids)
    if not activity_ids:
        return []
    labels = dict(DailyDebriefChallenge._meta.get_field("challenge_type").choices)
    rows = (
        DailyDebriefChallenge.objects.filter(
            debrief__activity_links__activity_id__in=activity_ids,
            debrief__deleted_at__isnull=True,
            debrief__is_restricted_incident=False,
        )
        .values("challenge_type")
        .annotate(n=Count("id", distinct=True))
        .order_by("-n", "challenge_type")[:8]
    )
    return [
        {
            "theme": str(labels.get(r["challenge_type"], r["challenge_type"])),
            "n": r["n"],
        }
        for r in rows
    ]


def _latest_feedback(activity_ids, limit: int = 5) -> list[dict]:
    """The newest visit feedback on the activities (or on the school visit a
    training was paired with)."""
    from apps.activities.models import SchoolVisitFeedback

    activity_ids = list(activity_ids)
    if not activity_ids:
        return []
    rows = (
        SchoolVisitFeedback.objects.filter(
            Q(activity_id__in=activity_ids)
            | Q(activity__paired_in_school_training__id__in=activity_ids)
        )
        .select_related("activity__school")
        .order_by("-created_at")[:limit]
    )
    return [
        {
            "school_id": row.activity.school_id,
            "school": row.activity.school.name if row.activity.school_id else "",
            "on": row.created_at,
            "finding": row.finding,
            "improvements": ", ".join(str(i) for i in (row.improvements or [])[:5]),
        }
        for row in rows
    ]


# ── Training ────────────────────────────────────────────────────────────────


def _partner_names(ids) -> dict:
    from apps.partners.models import Partner

    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(Partner.all_objects.filter(id__in=ids).values_list("id", "name"))


def _group_key(row: dict) -> str:
    item = row.get("catalogue_item_id") or f"type-{row.get('activity_type')}"
    return f"{item}|{row.get('delivery_mode') or 'other'}|{row.get('partner_id') or 'staff'}"


def _group_name(row: dict) -> str:
    return row.get("catalogue_name") or ACTIVITY_TYPE_LABELS.get(
        row.get("activity_type"), "Training"
    )


def _period_bounds(pop: Population):
    from apps.core.fy import get_fy_date_range

    start, _ = get_fy_date_range(pop.prev_fy)
    _, end = get_fy_date_range(pop.fy)
    return start.date(), end.date()


def _reached_frame(
    pop: Population, activity_types, extra_q: Q | None = None
) -> list[dict]:
    """IA-verified activities of `activity_types` dated in the two financial
    years compared, attributed to the reader's schools: one query. The same
    programme identity as the exposure frame."""
    from django.db.models.functions import Coalesce

    from apps.activities.models import Activity
    from apps.analytics.impact_engine import _programme_identity
    from apps.targets.my_targets import IA_VERIFIED_STATUSES

    ids = pop.school_ids
    if not ids:
        return []
    start, end = _period_bounds(pop)
    qs = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            status__in=IA_VERIFIED_STATUSES,
        )
        .filter(Q(school_id__in=ids) | Q(attended_school_ids__overlap=ids))
        .annotate(analysis_date=Coalesce("actual_delivery_date", "planned_date"))
        .filter(analysis_date__gte=start, analysis_date__lte=end)
    )
    if activity_types is not None:
        qs = qs.filter(activity_type__in=activity_types)
    if extra_q is not None:
        qs = qs.filter(extra_q)
    scoped = set(ids)
    out = []
    for act in qs.values(
        "id",
        "school_id",
        "attended_school_ids",
        "activity_type",
        "delivery_type",
        "cluster_id",
        "programme_delivery_mode",
        "assigned_partner_id",
        "project_id",
        "catalogue_item_id",
        "catalogue_item__display_name",
        "catalogue_item__programme_category",
        "training_course_id",
        "training_course__display_name",
        "training_course__programme_category",
    ):
        schools = (
            [act["school_id"]]
            if act["school_id"]
            else [s for s in (act["attended_school_ids"] or []) if s in scoped]
        )
        out.append(
            {
                "activity_id": act["id"],
                "activity_type": act["activity_type"],
                "schools": set(schools) & scoped,
                **_programme_identity(act),
            }
        )
    return out


def _observations(principal, activity_ids) -> list[dict]:
    """Shared Regional Lead training observations the reader may read, for
    these activities: one query (apps.cce_leadership.services.feedback_visible_to)."""
    from apps.cce_leadership.models import OBSERVATION_CRITERIA
    from apps.cce_leadership.services import feedback_visible_to

    activity_ids = list(activity_ids)
    if not activity_ids:
        return []
    fields = [name for name, _label, _help in OBSERVATION_CRITERIA]
    return list(
        feedback_visible_to(principal)
        .filter(activity_id__in=activity_ids)
        .values("activity_id", "recommendation", "held_on", *fields)
    )


def _rubric(observations: list[dict]) -> dict:
    from apps.cce_leadership.models import (
        OBSERVATION_CRITERIA,
        ObservationRecommendation,
    )

    fields = [name for name, _label, _help in OBSERVATION_CRITERIA]
    scores = [
        mean(values)
        for values in (
            [o[f] for f in fields if o.get(f) is not None] for o in observations
        )
        if values
    ]
    labels = dict(ObservationRecommendation.choices)
    recs = Counter(o["recommendation"] for o in observations if o["recommendation"])
    return {
        "observed": len(observations),
        "mean_rubric": round(mean(scores), 1) if scores else None,
        "recommendations": ", ".join(
            f"{labels.get(k, k)} {v}" for k, v in recs.most_common()
        ),
    }


def training_tab(principal, pop: Population, filters: dict) -> dict:
    from apps.analytics.attribution_service import intervention_contribution

    acts = pop.acts
    trainings = (
        acts[(acts["kind"] == "training")].to_dict("records") if not acts.empty else []
    )
    focused = [r for r in trainings if r["focus"]]
    any_pairs = {(r["school_id"], i) for r in focused for i in r["focus"]}
    reached_rows = _reached_frame(pop, TRAINING_TYPES)
    partner_names = _partner_names(
        {r["partner_id"] for r in reached_rows} | {r["partner_id"] for r in trainings}
    )

    groups: dict[str, dict] = {}

    def group(row):
        key = _group_key(row)
        if key not in groups:
            groups[key] = {
                "key": key,
                "name": _group_name(row),
                "item": row.get("catalogue_item_id")
                or f"type-{row.get('activity_type')}",
                "mode": row.get("delivery_mode") or "other",
                "partner": row.get("partner_id") or "staff",
                "partner_label": partner_names.get(row.get("partner_id"), "Partner")
                if row.get("partner_id")
                else "Edify staff",
                "pairs": set(),
                "interventions": set(),
                "reached": set(),
                "activity_ids": set(),
                "window_activity_ids": set(),
            }
        return groups[key]

    for row in reached_rows:
        g = group(row)
        g["reached"] |= row["schools"]
        g["activity_ids"].add(row["activity_id"])
    for row in focused:
        g = group(row)
        g["window_activity_ids"].add(row["activity_id"])
        for intervention in row["focus"]:
            g["pairs"].add((row["school_id"], intervention))
            g["interventions"].add(intervention)
        # A school measured in the window was reached, whichever FY dated it.
        g["reached"].add(row["school_id"])

    # Filters are offered from what exists and reach the table below.
    item_options = sorted(
        {(g["item"], g["name"]) for g in groups.values()}, key=lambda o: o[1]
    )
    mode_options = sorted(
        {
            (g["mode"], DELIVERY_MODE_LABELS.get(g["mode"], g["mode"]))
            for g in groups.values()
        },
        key=lambda o: o[1],
    )
    partner_options = sorted(
        {(g["partner"], g["partner_label"]) for g in groups.values()},
        key=lambda o: o[1],
    )
    item = filters.get("item") if filters.get("item") in dict(item_options) else ""
    mode = filters.get("mode") if filters.get("mode") in dict(mode_options) else ""
    partner = (
        filters.get("partner")
        if filters.get("partner") in dict(partner_options)
        else ""
    )

    rows = []
    ordered = sorted(
        groups.values(), key=lambda g: (g["name"], g["mode"], g["partner_label"])
    )
    for g in ordered:
        rows.append(
            compare(
                pop.imp,
                key=f"training:{g['key']}",
                label=g["name"],
                detail=f"{DELIVERY_MODE_LABELS.get(g['mode'], g['mode'])} · {g['partner_label']}",
                interventions=g["interventions"],
                exposed_pairs=g["pairs"],
                any_exposed_pairs=any_pairs,
                reached=len(g["reached"]),
            )
        )
    # The family is every group the data holds; a filter narrows what is shown,
    # never the correction.
    finish_rows(
        rows, period=pop.period, design=COMPARISON_DESIGN, caveat=ASSOCIATION_CAVEAT
    )
    selected = [
        g
        for g in groups.values()
        if (not item or g["item"] == item)
        and (not mode or g["mode"] == mode)
        and (not partner or g["partner"] == partner)
    ]
    selected_keys = {f"training:{g['key']}" for g in selected}
    activity_ids = (
        set().union(*(g["activity_ids"] | g["window_activity_ids"] for g in selected))
        if selected
        else set()
    )
    observations = _observations(principal, activity_ids)
    by_activity: dict[str, list[dict]] = defaultdict(list)
    for o in observations:
        by_activity[o["activity_id"]].append(o)
    for row, g in zip(rows, ordered):
        row["quality"] = _rubric(
            [
                o
                for a in (g["activity_ids"] | g["window_activity_ids"])
                for o in by_activity.get(a, [])
            ]
        )
        row["deliveries"] = len(g["activity_ids"] | g["window_activity_ids"])

    return {
        "outputs": {
            "verified_trainings": len(activity_ids),
            "schools_reached": len(set().union(*(g["reached"] for g in selected)))
            if selected
            else 0,
            "observations": len(observations),
        },
        "rows": [r for r in rows if r["key"] in selected_keys],
        "all_rows": rows,
        "contribution": intervention_contribution(
            pop.imp,
            pop.acts,
            countries=pop.countries,
            schools_in_scope=pop.schools_in_scope,
            confirmed_share=1.0,
        ),
        "qualitative": {
            "themes": _themes(activity_ids),
            "feedback": _latest_feedback(activity_ids),
            "quality": _rubric(observations),
            "quality_note": OBSERVATION_NOTE,
        },
        "filters": [
            _filter("item", "Training", item, "Every training", item_options),
            _filter("mode", "Delivery", mode, "Every delivery mode", mode_options),
            _filter(
                "partner",
                "Delivered by",
                partner,
                "Staff and partners",
                partner_options,
            ),
        ],
        "caveats": [ASSOCIATION_CAVEAT],
    }


def _filter(name, label, value, blank, options) -> dict:
    return {
        "name": name,
        "label": label,
        "value": value,
        "blank": blank,
        # One choice is nothing to choose: the control is not drawn.
        "options": list(options) if len(options) > 1 else [],
    }


# ── Lending ─────────────────────────────────────────────────────────────────


def _disbursements(
    principal, pop: Population, *, edtech_only: bool = False
) -> list[dict]:
    """First non-reversed disbursement per (school, purpose) for loans the
    reader's impact reach holds at their schools: one query."""
    from apps.business_transformation.lending_impact import scoped_impact_loans
    from apps.business_transformation.models import LoanDisbursement

    if not pop.school_ids:
        return []
    loans = scoped_impact_loans(principal).filter(school_id__in=pop.school_ids)
    qs = LoanDisbursement.objects.filter(
        loan_id__in=loans.values("id"), reversal__isnull=True
    )
    if edtech_only:
        qs = qs.filter(loan__purpose__is_edtech=True)
    first: dict[tuple, dict] = {}
    for row in qs.order_by("disbursed_on").values(
        "loan_id",
        "loan__school_id",
        "loan__purpose_id",
        "loan__purpose__label",
        "loan__purpose__follow_up_days",
        "loan__purpose__is_edtech",
        "disbursed_on",
    ):
        first.setdefault((row["loan__school_id"], row["loan__purpose_id"]), row)
    return list(first.values())


def lending_tab(principal, pop: Population, filters: dict) -> dict:
    from apps.business_transformation.lending_impact import scoped_impact_loans
    from apps.business_transformation.models import (
        EnrolmentSnapshot,
        EnrolmentSnapshotKind,
        IAValidationStatus,
        ImpactEvidenceStatus,
        LoanImpactAssessment,
        LoanImpactStatus,
        LoanPurposeAllocation,
        PurposeAllocationStatus,
    )

    windows = _windows(pop.imp)
    disb = _disbursements(principal, pop)
    purposes = {}
    for row in disb:
        purposes.setdefault(
            row["loan__purpose_id"] or "none",
            row["loan__purpose__label"] or "No purpose recorded",
        )
    purpose_options = sorted(purposes.items(), key=lambda o: o[1])
    purpose = filters.get("purpose") if filters.get("purpose") in purposes else ""

    financed_any = {
        (row["loan__school_id"])
        for row in disb
        if row["loan__school_id"] in windows
        and row["disbursed_on"] <= windows[row["loan__school_id"]]["window_end"]
    }
    any_pairs = {(s, d) for s in financed_any for d in LENDING_DOMAINS}
    rows = []
    groups = [("all", "Every loan purpose")] + purpose_options
    for key, label in groups:
        exposed, immature = set(), False
        for row in disb:
            pid = row["loan__purpose_id"] or "none"
            if key != "all" and pid != key:
                continue
            school = row["loan__school_id"]
            if not _in_window(windows, school, row["disbursed_on"]):
                continue
            exposed.add(school)
            days = (windows[school]["window_end"] - row["disbursed_on"]).days
            if days < (row["loan__purpose__follow_up_days"] or 0):
                immature = True
        for domain in LENDING_DOMAINS:
            rows.append(
                compare(
                    pop.imp,
                    key=f"lending:{key}:{domain}",
                    label=label,
                    detail=INTERVENTION_LABELS[domain],
                    interventions=[domain],
                    exposed_pairs={(s, domain) for s in exposed},
                    any_exposed_pairs=any_pairs,
                    reached=len(exposed),
                    flags=(es.IMMATURE_COHORT,) if immature else (),
                )
            )
    finish_rows(
        rows, period=pop.period, design=COMPARISON_DESIGN, caveat=LENDING_CAVEAT
    )
    shown = [r for r in rows if r["key"].split(":")[1] == (purpose or "all")]

    loans = scoped_impact_loans(principal).filter(school_id__in=pop.school_ids)
    conclusions = LoanImpactAssessment.objects.filter(
        loan_id__in=loans.values("id"), ia_status=IAValidationStatus.VERIFIED
    )
    if purpose and purpose != "none":
        conclusions = conclusions.filter(loan__purpose_id=purpose)
    labels = dict(LoanImpactStatus.choices)
    by_class = [
        {
            "classification": str(labels.get(r["classification"], r["classification"])),
            "n": r["n"],
        }
        for r in conclusions.values("classification")
        .annotate(n=Count("id"))
        .order_by("-n")
    ]
    narratives = [
        {
            "school_id": a.loan.school_id,
            "school": a.loan.school.name,
            "classification": a.get_classification_display(),
            "narrative": a.narrative,
            "limitations": a.limitations,
            "on": a.ia_verified_at,
        }
        for a in conclusions.select_related("loan__school").order_by("-ia_verified_at")[
            :5
        ]
    ]
    snapshot_pairs = []
    verified = (
        EnrolmentSnapshot.objects.filter(
            loan_id__in=loans.values("id"), status=ImpactEvidenceStatus.VERIFIED
        )
        .order_by("loan_id", "as_of_date")
        .values("loan_id", "kind", "learner_count")
    )
    by_loan: dict[str, dict] = defaultdict(dict)
    for s in verified:
        if s["kind"] == EnrolmentSnapshotKind.BASELINE:
            by_loan[s["loan_id"]].setdefault("baseline", s["learner_count"])
        else:
            by_loan[s["loan_id"]]["follow_up"] = s["learner_count"]
    for pair in by_loan.values():
        if pair.get("baseline") and pair.get("follow_up") is not None:
            snapshot_pairs.append(
                (pair["follow_up"] - pair["baseline"]) / pair["baseline"] * 100
            )
    loan_ids = loans.values("id")
    return {
        "outputs": {
            "schools_financed": len({r["loan__school_id"] for r in disb}),
            "use_verified": LoanPurposeAllocation.objects.filter(
                loan_id__in=loan_ids, status=PurposeAllocationStatus.VERIFIED
            ).count(),
            "conclusions_verified": conclusions.count(),
        },
        "rows": shown,
        "all_rows": rows,
        "qualitative": {
            "classifications": by_class,
            "narratives": narratives,
            "enrolment": {
                "loans": len(snapshot_pairs),
                "median_change_pct": round(median(snapshot_pairs), 1)
                if snapshot_pairs
                else None,
                "grade": es.grade(len(snapshot_pairs), confirmed_share=1.0),
            },
        },
        "filters": [
            _filter(
                "purpose",
                "Loan purpose",
                purpose,
                "Every loan purpose",
                purpose_options,
            ),
        ],
        "caveats": [ASSOCIATION_CAVEAT, LENDING_CAVEAT],
    }


# ── EdTech ──────────────────────────────────────────────────────────────────


def _edtech_deployments(pop: Population) -> list[dict]:
    from apps.impact.models import EdTechDeployment, EvidenceVerification

    if not pop.school_ids:
        return []
    return list(
        EdTechDeployment.objects.filter(
            school_id__in=pop.school_ids,
            verification_status=EvidenceVerification.CONFIRMED,
        ).values("id", "school_id", "deployed_on", "quantity")
    )


def _edtech_checks(pop: Population) -> dict:
    """The latest confirmed check of each confirmed deployment in scope, and
    the newest issues reported: two queries."""
    from django.db.models import Subquery

    from apps.impact.models import EdTechCheck, EdTechDeployment, EvidenceVerification

    confirmed = EvidenceVerification.CONFIRMED
    if not pop.school_ids:
        return {
            "deployments": 0,
            "checked": 0,
            "units_checked": 0,
            "units_functional": 0,
            "functional_pct": None,
            "teachers_using": 0,
            "learners_using": 0,
            "issues": [],
        }
    latest = EdTechCheck.objects.filter(
        deployment_id=OuterRef("pk"), verification_status=confirmed
    ).order_by("-checked_on", "-created_at")
    rows = list(
        EdTechDeployment.objects.filter(
            school_id__in=pop.school_ids, verification_status=confirmed
        )
        .annotate(
            _checked=Exists(latest),
            _functional=Subquery(latest.values("units_functional")[:1]),
            _teachers=Subquery(latest.values("teachers_using")[:1]),
            _learners=Subquery(latest.values("learners_using")[:1]),
        )
        .values("quantity", "_checked", "_functional", "_teachers", "_learners")
    )
    checked = [r for r in rows if r["_checked"]]
    units_checked = sum(r["quantity"] for r in checked)
    functional = sum(r["_functional"] or 0 for r in checked)
    issues = [
        {"school": c.deployment.school.name, "on": c.checked_on, "issues": c.issues}
        for c in EdTechCheck.objects.filter(
            deployment__school_id__in=pop.school_ids,
            verification_status=confirmed,
        )
        .exclude(issues="")
        .select_related("deployment__school")
        .order_by("-checked_on")[:5]
    ]
    return {
        "deployments": len(rows),
        "checked": len(checked),
        "units_checked": units_checked,
        "units_functional": functional,
        "functional_pct": percentage(functional, units_checked),
        "teachers_using": sum(r["_teachers"] or 0 for r in checked),
        "learners_using": sum(r["_learners"] or 0 for r in checked),
        "issues": issues,
    }


def edtech_tab(principal, pop: Population, filters: dict) -> dict:
    windows = _windows(pop.imp)
    acts = pop.acts.to_dict("records") if not pop.acts.empty else []
    sources: dict[str, dict] = {
        "trainings": {"label": "EdTech trainings", "exposed": set(), "reached": set()},
        "project": {
            "label": "EdTech Pilot project (SP-EDTECH)",
            "exposed": set(),
            "reached": set(),
        },
        "loans": {"label": "EdTech loans", "exposed": set(), "reached": set()},
        "deployments": {
            "label": "Confirmed deployments",
            "exposed": set(),
            "reached": set(),
        },
    }
    edtech_window_ids = set()
    for row in acts:
        if row["programme_category"] == EDTECH_PROGRAMME_CATEGORY:
            sources["trainings"]["exposed"].add(row["school_id"])
            edtech_window_ids.add(row["activity_id"])
        if row["project_code"] == EDTECH_PROJECT_CODE:
            sources["project"]["exposed"].add(row["school_id"])
            edtech_window_ids.add(row["activity_id"])
    for row in _disbursements(principal, pop, edtech_only=True):
        sources["loans"]["reached"].add(row["loan__school_id"])
        if _in_window(windows, row["loan__school_id"], row["disbursed_on"]):
            sources["loans"]["exposed"].add(row["loan__school_id"])
    deployments = _edtech_deployments(pop)
    for row in deployments:
        sources["deployments"]["reached"].add(row["school_id"])
        if _in_window(windows, row["school_id"], row["deployed_on"]):
            sources["deployments"]["exposed"].add(row["school_id"])
    reached_acts = _reached_frame(
        pop,
        None,
        Q(catalogue_item__programme_category=EDTECH_PROGRAMME_CATEGORY)
        | Q(training_course__programme_category=EDTECH_PROGRAMME_CATEGORY)
        | Q(project_id__in=_edtech_project_ids()),
    )
    for row in reached_acts:
        if row["programme_category"] == EDTECH_PROGRAMME_CATEGORY:
            sources["trainings"]["reached"] |= row["schools"]
        if row["project_code"] == EDTECH_PROJECT_CODE:
            sources["project"]["reached"] |= row["schools"]
    for source in sources.values():
        source["reached"] |= source["exposed"]
    any_exposed = set().union(*(s["exposed"] for s in sources.values()))
    any_reached = set().union(*(s["reached"] for s in sources.values()))
    any_pairs = {(s, LEARNING_ENVIRONMENT) for s in any_exposed}
    source_options = [(k, v["label"]) for k, v in sources.items()]
    source = (
        filters.get("source") if filters.get("source") in dict(source_options) else ""
    )

    rows = [
        compare(
            pop.imp,
            key="edtech:any",
            label="Any EdTech exposure",
            detail="Trainings, the pilot project, loans or deployments",
            interventions=[LEARNING_ENVIRONMENT],
            exposed_pairs=any_pairs,
            any_exposed_pairs=any_pairs,
            reached=len(any_reached),
            flags=(es.PROXY_MEASURE,),
        )
    ]
    for key, s in sources.items():
        rows.append(
            compare(
                pop.imp,
                key=f"edtech:{key}",
                label=s["label"],
                detail=INTERVENTION_LABELS[LEARNING_ENVIRONMENT],
                interventions=[LEARNING_ENVIRONMENT],
                exposed_pairs={(sid, LEARNING_ENVIRONMENT) for sid in s["exposed"]},
                any_exposed_pairs=any_pairs,
                reached=len(s["reached"]),
                flags=(es.PROXY_MEASURE,),
            )
        )
    finish_rows(rows, period=pop.period, design=COMPARISON_DESIGN, caveat=EDTECH_CAVEAT)
    shown = [
        r for r in rows if not source or r["key"] in ("edtech:any", f"edtech:{source}")
    ]
    checks = _edtech_checks(pop)
    return {
        "outputs": {
            "verified_trainings": len(
                {r["activity_id"] for r in reached_acts} | edtech_window_ids
            ),
            "deployments": checks["deployments"],
            "functional_pct": checks["functional_pct"],
            "units_checked": checks["units_checked"],
            "loans": len(sources["loans"]["reached"]),
        },
        "rows": shown,
        "all_rows": rows,
        "checks": checks,
        "qualitative": {
            "themes": _themes(
                {r["activity_id"] for r in reached_acts} | edtech_window_ids
            ),
            "feedback": _latest_feedback(
                {r["activity_id"] for r in reached_acts} | edtech_window_ids
            ),
        },
        "filters": [
            _filter("source", "Exposure", source, "Every exposure", source_options),
        ],
        "caveats": [EDTECH_CAVEAT, ASSOCIATION_CAVEAT],
    }


def _edtech_project_ids():
    from apps.projects.models import Project

    return Project.objects.filter(code=EDTECH_PROJECT_CODE).values("id")


# ── Visits ──────────────────────────────────────────────────────────────────


def visits_tab(principal, pop: Population, filters: dict) -> dict:
    """Focused school visits, on the impact engine's own per-intervention
    comparison, beside the canonical School Visit Effectiveness summary."""
    from apps.analytics.impact_engine import dosage_impact
    from apps.analytics.visit_effectiveness_engine import (
        SchoolVisitEffectivenessAnalyticsService,
    )

    acts = pop.acts
    visits = acts[acts["kind"] == "visit"] if not acts.empty else acts
    dosage = (
        dosage_impact(pop.imp, acts, "visit")
        if not pop.imp.empty
        else {"per_intervention": []}
    )
    intervention_options = [
        (r["key"], r["label"]) for r in dosage["per_intervention"] if r["n_treated"]
    ]
    intervention = (
        filters.get("intervention")
        if filters.get("intervention") in dict(intervention_options)
        else ""
    )
    rows = []
    for r in dosage["per_intervention"]:
        graded = r["grade"]
        rows.append(
            {
                "key": f"visits:{r['key']}",
                "label": r["label"],
                "detail": "Focused verified visits",
                "outcome": r["label"],
                "intervention": r["key"],
                "exposed_n": r["n_treated"],
                "comparison_n": r["n_untreated"],
                "reached": None,
                "coverage_pct": None,
                "missing_pct": None,
                "median_exposed": r["median_treated"],
                "median_comparison": r["median_untreated"],
                "difference": r["effect"],
                "p": r["p"],
                "p_adjusted": r["p_adjusted"],
                "verdict": r["verdict"],
                "period": pop.period,
                "design": COMPARISON_DESIGN,
                "grade": graded["grade"],
                "grade_label": graded["label"],
                "grade_reasons": graded["reasons"],
                "grade_tone": es.grade_tone(graded["grade"]),
                "caveat": ASSOCIATION_CAVEAT,
            }
        )
    shown = [r for r in rows if not intervention or r["intervention"] == intervention]
    effectiveness = SchoolVisitEffectivenessAnalyticsService.build_dashboard(
        principal, {}
    )
    association = effectiveness.get("association") or {}
    cohort = effectiveness.get("cohort") or {}
    visit_ids = set(visits["activity_id"]) if not visits.empty else set()
    return {
        "outputs": {
            "verified_visits": len(visit_ids),
            "schools_visited": int(visits["school_id"].nunique())
            if not visits.empty
            else 0,
        },
        "rows": shown,
        "all_rows": rows,
        "effectiveness": {
            "comparable_schools": cohort.get("comparable_schools", 0),
            "baseline_fy": (effectiveness.get("methodology") or {}).get("baseline_fy"),
            "followup_fy": (effectiveness.get("methodology") or {}).get("followup_fy"),
            "excluded_fys": ", ".join(
                (effectiveness.get("methodology") or {}).get("excluded_fys") or []
            ),
            "verdict": association.get("verdict"),
            "r": association.get("r"),
            "p": association.get("p"),
            "n": association.get("n"),
            "grade": es.grade(int(association.get("n") or 0), confirmed_share=1.0),
        },
        "qualitative": {
            "themes": _themes(visit_ids),
            "feedback": _latest_feedback(visit_ids),
        },
        "filters": [
            _filter(
                "intervention",
                "Intervention",
                intervention,
                "Every intervention",
                intervention_options,
            ),
        ],
        "caveats": [ASSOCIATION_CAVEAT],
    }


BUILDERS = {
    TRAINING: training_tab,
    LENDING: lending_tab,
    EDTECH: edtech_tab,
    VISITS: visits_tab,
}


def build(principal, programme: str, filters: dict | None = None) -> dict:
    """One tab of Programme Learning for `principal`.

    Returns {"programme", "fy", "prev_fy", "period", "fy_options",
    "coverage", "outputs", "rows", "qualitative", "filters", "caveats", ...}.
    The Findings tab needs no population and is built by the view."""
    filters = dict(filters or {})
    if programme not in BUILDERS:
        raise ValueError(f"unknown programme {programme!r}")
    fy = resolve_fy(filters.get("fy"))
    pop = population(principal, fy)
    data = BUILDERS[programme](principal, pop, filters)
    data.update(
        {
            "programme": programme,
            "fy": fy,
            "prev_fy": pop.prev_fy,
            "period": pop.period,
            "fy_options": fy_choices(),
            "coverage": {
                "schools_in_scope": pop.schools_in_scope,
                "schools_paired": pop.paired,
                "pairs_too_close": pop.too_close,
            },
        }
    )
    return data


def row_by_key(
    principal, row_key: str, filters: dict | None = None
) -> tuple[dict, dict] | tuple[None, None]:
    """Recompute the tab a row key belongs to and return (row, cohort
    filters) — the server's own figures for a finding's snapshot."""
    programme = (row_key or "").split(":", 1)[0]
    if programme not in BUILDERS:
        return None, None
    filters = {k: v for k, v in dict(filters or {}).items() if k in ("fy",)}
    data = build(principal, programme, filters)
    cohort = {"fy": data["fy"], "period": data["period"], "programme": programme}
    for row in data.get("all_rows") or data["rows"]:
        if row["key"] == row_key:
            return row, cohort
    return None, None
