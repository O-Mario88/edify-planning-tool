"""Statistical impact-intelligence engine (pandas + scipy).

Answers the questions the aggregation dashboards cannot: did visits,
trainings, and money actually MOVE the SSA intervention scores — and where
they didn't, what does the field say is in the way?

Analysis families (all computed per role-scoped school set, per FY cycle):
  1. Visit dosage vs intervention improvement (dose-response + stratified
     treated/untreated comparison).
  2. Training dosage vs intervention improvement (same design).
  3. Accepted spend vs improvement — cost per score point, efficiency
     quadrants.
  4. Staff target achievement vs improvement of the schools they support.
  5. Geography: district × intervention performance with a Kruskal-Wallis
     test of whether districts genuinely differ.
  6. Field-debrief reality overlay: for stuck interventions, what the
     debriefs report (critical counts, top challenge types).
  7. Five programme-driver associations: partner activities,
     intervention-linked trainings, staff activities, cluster meetings, and
     special-project work. Results can be grouped by PL, sub-region, district,
     cluster, sub-county, and populated parishes.

Method constraints (each shows up in `method_notes` on the page):
- "Improvement" is the per (school, intervention) delta between the
  confirmed SSA of the selected FY and the confirmed SSA of the previous
  FY (upload enforces one SSA per school per FY). A school's exposure
  window is (previous assessment date .. current assessment date]; only
  executed activities dated inside the window count as dosage.
- The activity-creation gate only allows focusing an intervention the
  school is already weak in (score < 7.0 or two weakest — see
  apps/activities/services.py create()), so treated schools start lower by
  construction. Naive treated-vs-all comparison would measure regression
  to the mean. Every treated/untreated comparison is therefore restricted
  to the weak-baseline stratum (previous score < 7.0) on that intervention.
- Money is plain integer UGX. Accepted spend = AdvanceRequest in
  {accounted, reimbursed} (accounted_amount) plus PartnerPayment.amount_paid
  — the accountant-accepted, NetSuite-referenced rows only. Cluster
  activities split their spend equally across attributed schools.
- Rank-based statistics throughout (Spearman, Mann-Whitney U,
  Kruskal-Wallis): score deltas are bounded, skewed, and small-sample.
  Groups below MIN_GROUP_N report "insufficient data" — never a number.
"""

from __future__ import annotations

import json
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd
from django.db.models import Q
from django.db.models.functions import Coalesce
from scipy import stats

from apps.accounts.models import StaffSchoolAssignment
from apps.activities.models import Activity
from apps.analytics.decision_engine import (
    DECLINE_THRESHOLD,
    IMPROVEMENT_THRESHOLD,
)
from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_WORK_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)
from apps.analytics.platform_engine import describe_numeric, engine_metadata
from apps.core.enums import SsaIntervention, VerificationStatus
from apps.core.fy import fy_options, get_operational_fy
from apps.core.scoping import resolve_user_scope
from apps.debriefs.field_debrief_service import FieldDebriefService
from apps.debriefs.models import DailyDebriefChallenge
from apps.fund_requests.finance_models import PartnerPayment
from apps.fund_requests.models import AdvanceRequest
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.targets.my_targets import (
    active_target_areas,
    per_user_monthly_series,
    weighted_period_pct,
)

# Statistical honesty floors: below these, the engine says "insufficient
# data" instead of reporting a number nobody should act on.
MIN_GROUP_N = 8  # smallest group size for a two-group comparison
MIN_CORR_N = 10  # smallest sample for a correlation

#: Shared empty result for a (district, intervention) cell with no rows —
#: allocated once so a lookup miss costs nothing.
_EMPTY_DELTAS = np.array([], dtype=float)
SIGNIFICANT_P = 0.05
SUGGESTIVE_P = 0.10

# Mirrors the create()-gate weakness bar (score < 7.0) — the stratification
# boundary for treated/untreated comparisons.
WEAK_BASELINE = 7.0

# Advance statuses whose accounted_amount is accountant-accepted spend.
ACCEPTED_ADVANCE_STATUSES = ("accounted", "reimbursed")

INTERVENTION_LABELS = {i.value: i.label for i in SsaIntervention}
ALL_INTERVENTIONS = [i.value for i in SsaIntervention]

DOSAGE_BUCKETS = ((0, 0, "0"), (1, 2, "1–2"), (3, None, "3+"))

DRIVER_DEFINITIONS = (
    (
        "partner",
        "Partner activities",
        "Partner-delivered verified activities",
    ),
    (
        "training",
        "SSA-linked trainings",
        "Verified trainings linked to at least one SSA intervention",
    ),
    (
        "staff",
        "Staff activities",
        "Staff-delivered verified activities",
    ),
    (
        "cluster_meeting",
        "Cluster meetings",
        "Verified cluster meetings attributed to attending schools",
    ),
    (
        "special_project",
        "Special projects",
        "Verified work explicitly linked to a special project",
    ),
)

GROUP_LABELS = {
    "pl": "Program Lead",
    "sub_region": "Sub-region",
    "district": "District",
    "cluster": "Cluster",
    "sub_county": "Sub-county",
    "parish": "Parish",
}

COUNTRY_DRIVER_ROLES = {
    "Admin",
    "CountryDirector",
    "ImpactAssessment",
    "RegionalVicePresident",
    "Accountant",
}


# ── Scope (same shape as ssa_performance_service — correct RVP handling) ─────


def _scoped_schools(principal):
    """Return the portfolio population authorized for contribution analytics.

    Field staff and PLs use the shared own/team portfolio scope. The explicitly
    country-facing analysis roles requested by programme leadership (IA, CD,
    RVP and Accountant) aggregate the whole country; RVP identity suppression
    remains enforced separately through ``can_view_school_level_detail``.
    """
    from apps.core.scoping import scoped_school_queryset

    scope = resolve_user_scope(principal)
    schools = School.objects.filter(deleted_at__isnull=True)
    if getattr(principal, "active_role", "") in COUNTRY_DRIVER_ROLES:
        return schools, scope
    return scoped_school_queryset(scope, schools), scope


# ── Frame builders ────────────────────────────────────────────────────────────


def _latest_confirmed_records(school_ids: list[str], fy: str) -> dict[str, dict]:
    """Latest confirmed SSA record per school for one FY (upload enforces one
    per FY; newest-first dedupe keeps this robust against legacy duplicates)."""
    rows = (
        SsaRecord.objects.filter(
            school_id__in=school_ids,
            fy=fy,
            deleted_at__isnull=True,
            verification_status=VerificationStatus.CONFIRMED.value,
        )
        .values("id", "school_id", "date_of_ssa")
        .order_by("school_id", "-date_of_ssa", "-created_at")
    )
    latest: dict[str, dict] = {}
    for row in rows:
        latest.setdefault(row["school_id"], row)
    return latest


def improvement_frame(school_ids: list[str], fy: str) -> pd.DataFrame:
    """One row per (school, intervention) with both cycles present:
    columns school_id, intervention, prev_score, curr_score, delta,
    window_start, window_end (assessment dates bounding the exposure)."""
    prev_fy = str(int(fy) - 1)
    curr = _latest_confirmed_records(school_ids, fy)
    prev = _latest_confirmed_records(list(curr.keys()), prev_fy)
    paired_schools = [sid for sid in curr if sid in prev]
    if not paired_schools:
        return pd.DataFrame(
            columns=[
                "school_id",
                "intervention",
                "prev_score",
                "curr_score",
                "delta",
                "window_start",
                "window_end",
            ]
        )

    record_ids = [curr[s]["id"] for s in paired_schools] + [
        prev[s]["id"] for s in paired_schools
    ]
    scores: dict[str, dict[str, float]] = defaultdict(dict)
    for row in SsaScore.objects.filter(ssa_record_id__in=record_ids).values(
        "ssa_record_id", "intervention", "score"
    ):
        scores[row["ssa_record_id"]][row["intervention"]] = float(row["score"])

    rows = []
    for sid in paired_schools:
        prev_map = scores.get(prev[sid]["id"], {})
        curr_map = scores.get(curr[sid]["id"], {})
        for intervention in ALL_INTERVENTIONS:
            if intervention not in prev_map or intervention not in curr_map:
                continue
            rows.append(
                {
                    "school_id": sid,
                    "intervention": intervention,
                    "prev_score": prev_map[intervention],
                    "curr_score": curr_map[intervention],
                    "delta": curr_map[intervention] - prev_map[intervention],
                    "window_start": prev[sid]["date_of_ssa"].date(),
                    "window_end": curr[sid]["date_of_ssa"].date(),
                }
            )
    return pd.DataFrame(rows)


def _activity_focus_set(row: dict) -> set[str]:
    focus = set()
    if row["focus_intervention"]:
        focus.add(row["focus_intervention"])
    elif row["purpose_intervention"]:  # legacy mirror, old rows only
        focus.add(row["purpose_intervention"])
    for extra in row["secondary_focus_interventions"] or []:
        focus.add(extra)
    return focus


def activity_frame(imp: pd.DataFrame, school_ids: list[str]) -> pd.DataFrame:
    """Executed activities attributed per school, restricted to each school's
    exposure window. Cluster activities (school NULL) attribute through
    attended_school_ids; their spend is split equally across those schools.
    Columns: activity_id, school_id, kind, analysis_date, focus (set),
    delivery_type, is_special_project, accepted_spend (UGX share).

    ``analysis_date`` prefers the recorded delivery date and falls back to the
    planned date for legacy rows. A project-wide activity without a direct
    school/attendance list is attributed only to schools explicitly enrolled
    in that project at the time; this is the narrowest defensible fallback for
    historical project work that predates per-school attendance capture.
    """
    columns = [
        "activity_id",
        "school_id",
        "kind",
        "activity_type",
        "analysis_date",
        "focus",
        "delivery_type",
        "is_special_project",
        "accepted_spend",
    ]
    if imp.empty:
        return pd.DataFrame(columns=columns)
    windows = (
        imp.groupby("school_id")[["window_start", "window_end"]]
        .first()
        .to_dict("index")
    )
    lo = min(w["window_start"] for w in windows.values())
    hi = max(w["window_end"] for w in windows.values())

    from apps.projects.models import ProjectSchoolAssignment

    project_assignments = list(
        ProjectSchoolAssignment.objects.filter(school_id__in=school_ids).values(
            "project_id", "school_id", "start_date"
        )
    )
    project_ids = sorted({row["project_id"] for row in project_assignments})
    project_schools: dict[str, list[dict]] = defaultdict(list)
    for row in project_assignments:
        project_schools[row["project_id"]].append(row)

    activity_scope = Q(school_id__in=school_ids) | Q(
        attended_school_ids__overlap=school_ids
    )
    if project_ids:
        activity_scope |= Q(project_id__in=project_ids)

    activities = list(
        Activity.objects.filter(
            activity_scope,
            deleted_at__isnull=True,
            status__in=COMPLETED_WORK_STATUSES,
        )
        .annotate(analysis_date=Coalesce("actual_delivery_date", "planned_date"))
        .filter(
            analysis_date__isnull=False,
            analysis_date__gt=lo,
            analysis_date__lte=hi,
        )
        .values(
            "id",
            "school_id",
            "activity_type",
            "delivery_type",
            "focus_intervention",
            "purpose_intervention",
            "secondary_focus_interventions",
            "analysis_date",
            "attended_school_ids",
            "project_id",
            "primary_driver_type",
            "activity_context_type",
        )
    )
    if not activities:
        return pd.DataFrame(columns=columns)

    spend = _accepted_spend_by_activity([a["id"] for a in activities])
    scoped = set(school_ids)
    rows = []
    for act in activities:
        if act["activity_type"] in VISIT_TYPES:
            kind = "visit"
        elif act["activity_type"] in TRAINING_TYPES:
            kind = "training"
        else:
            kind = "other"
        if act["school_id"]:
            attributed = [act["school_id"]]
        elif act["attended_school_ids"]:
            attributed = [s for s in (act["attended_school_ids"] or []) if s in scoped]
        elif act["project_id"]:
            attributed = [
                row["school_id"]
                for row in project_schools.get(act["project_id"], [])
                if row["start_date"] is None
                or row["start_date"] <= act["analysis_date"]
            ]
        else:
            attributed = []
        attributed = [
            s
            for s in attributed
            if s in windows
            and windows[s]["window_start"]
            < act["analysis_date"]
            <= windows[s]["window_end"]
        ]
        if not attributed:
            continue
        share = spend.get(act["id"], 0) / len(attributed)
        focus = _activity_focus_set(act)
        is_special_project = bool(
            act["project_id"]
            or act["activity_type"] == "project_activity"
            or act["primary_driver_type"] == "special_project"
            or act["activity_context_type"] == "project"
        )
        for sid in attributed:
            rows.append(
                {
                    "activity_id": act["id"],
                    "school_id": sid,
                    "kind": kind,
                    "activity_type": act["activity_type"],
                    "analysis_date": act["analysis_date"],
                    "focus": focus,
                    "delivery_type": act["delivery_type"],
                    "is_special_project": is_special_project,
                    "accepted_spend": share,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _accepted_spend_by_activity(activity_ids: list[str]) -> dict[str, float]:
    """Accountant-accepted UGX per activity: accounted advances + partner
    payments. Never Disbursement rows (they mirror the same money)."""
    spend: dict[str, float] = defaultdict(float)
    for row in AdvanceRequest.objects.filter(
        activity_id__in=activity_ids, status__in=ACCEPTED_ADVANCE_STATUSES
    ).values("activity_id", "accounted_amount"):
        spend[row["activity_id"]] += float(row["accounted_amount"] or 0)
    for row in PartnerPayment.objects.filter(activity_id__in=activity_ids).values(
        "activity_id", "amount_paid"
    ):
        spend[row["activity_id"]] += float(row["amount_paid"] or 0)
    return dict(spend)


# ── Statistics helpers (always plain Python types out) ───────────────────────


def _verdict(p: float | None) -> str:
    if p is None:
        return "insufficient data"
    if p < SIGNIFICANT_P:
        return "significant"
    if p < SUGGESTIVE_P:
        return "suggestive"
    return "not significant"


def _spearman(x: pd.Series, y: pd.Series) -> dict:
    n = int(len(x))
    if n < MIN_CORR_N or x.nunique() < 2 or y.nunique() < 2:
        return {
            "rho": None,
            "p": None,
            "n": n,
            "ci_low": None,
            "ci_high": None,
            "verdict": "insufficient data",
        }
    rho, p = stats.spearmanr(x, y)
    if np.isnan(rho):
        return {
            "rho": None,
            "p": None,
            "n": n,
            "ci_low": None,
            "ci_high": None,
            "verdict": "insufficient data",
        }
    # Approximate 95% interval using Fisher's z transform. This is intentionally
    # labelled approximate in the UI: rank correlations and tied dosage counts
    # do not support false decimal precision, but a plausible range is still
    # more decision-useful than a point estimate alone.
    bounded_rho = min(0.999999, max(-0.999999, float(rho)))
    margin = 1.96 / np.sqrt(n - 3)
    z = np.arctanh(bounded_rho)
    ci_low, ci_high = np.tanh((z - margin, z + margin))
    return {
        "rho": round(float(rho), 3),
        "p": round(float(p), 4),
        "n": n,
        "ci_low": round(float(ci_low), 3),
        "ci_high": round(float(ci_high), 3),
        "verdict": _verdict(float(p)),
    }


def _mann_whitney(treated: pd.Series, untreated: pd.Series) -> dict:
    n_t, n_u = int(len(treated)), int(len(untreated))
    base = {
        "n_treated": n_t,
        "n_untreated": n_u,
        "median_treated": round(float(treated.median()), 2) if n_t else None,
        "median_untreated": round(float(untreated.median()), 2) if n_u else None,
    }
    if n_t < MIN_GROUP_N or n_u < MIN_GROUP_N:
        return {**base, "effect": None, "p": None, "verdict": "insufficient data"}
    try:
        _, p = stats.mannwhitneyu(treated, untreated, alternative="two-sided")
    except ValueError:  # all values identical
        return {**base, "effect": None, "p": None, "verdict": "insufficient data"}
    if np.isnan(p):
        return {**base, "effect": None, "p": None, "verdict": "insufficient data"}
    effect = float(treated.median()) - float(untreated.median())
    return {
        **base,
        "effect": round(effect, 2),
        "p": round(float(p), 4),
        "verdict": _verdict(float(p)),
    }


def _dosage_bucket(count: int) -> str:
    for lo, hi, label in DOSAGE_BUCKETS:
        if count >= lo and (hi is None or count <= hi):
            return label
    return DOSAGE_BUCKETS[-1][2]


# ── Analysis families ─────────────────────────────────────────────────────────


def _school_outcomes(imp: pd.DataFrame) -> pd.DataFrame:
    """Per-school mean delta across interventions (the school-level outcome)."""
    return imp.groupby("school_id")["delta"].mean().rename("mean_delta").reset_index()


def dosage_impact(imp: pd.DataFrame, acts: pd.DataFrame, kind: str) -> dict:
    """Dose-response + per-intervention stratified comparison for one
    activity kind ('visit' | 'training')."""
    outcomes = _school_outcomes(imp)
    of_kind = acts[acts["kind"] == kind] if not acts.empty else acts
    counts = (
        of_kind.groupby("school_id").size().rename("dosage").reset_index()
        if not of_kind.empty
        else pd.DataFrame(columns=["school_id", "dosage"])
    )
    merged = outcomes.merge(counts, on="school_id", how="left")
    merged["dosage"] = merged["dosage"].fillna(0).astype(int)

    corr = _spearman(merged["dosage"], merged["mean_delta"])

    buckets = []
    for _, _, label in DOSAGE_BUCKETS:
        grp = merged[merged["dosage"].map(_dosage_bucket) == label]["mean_delta"]
        buckets.append(
            {
                "label": label,
                "n": int(len(grp)),
                "median_delta": round(float(grp.median()), 2) if len(grp) else None,
            }
        )

    per_intervention = []
    for intervention in ALL_INTERVENTIONS:
        stratum = imp[
            (imp["intervention"] == intervention) & (imp["prev_score"] < WEAK_BASELINE)
        ]
        if stratum.empty:
            per_intervention.append(
                {
                    "key": intervention,
                    "label": INTERVENTION_LABELS[intervention],
                    "n_treated": 0,
                    "n_untreated": 0,
                    "median_treated": None,
                    "median_untreated": None,
                    "effect": None,
                    "p": None,
                    "verdict": "insufficient data",
                }
            )
            continue
        focused_schools = (
            set(of_kind[of_kind["focus"].map(lambda f: intervention in f)]["school_id"])
            if not of_kind.empty
            else set()
        )
        treated = stratum[stratum["school_id"].isin(focused_schools)]["delta"]
        untreated = stratum[~stratum["school_id"].isin(focused_schools)]["delta"]
        per_intervention.append(
            {
                "key": intervention,
                "label": INTERVENTION_LABELS[intervention],
                **_mann_whitney(treated, untreated),
            }
        )

    return {
        "kind": kind,
        "correlation": corr,
        "buckets": buckets,
        "per_intervention": per_intervention,
        "schools_with_any": int((merged["dosage"] > 0).sum()),
    }


def _driver_activity_rows(acts: pd.DataFrame, key: str) -> pd.DataFrame:
    if acts.empty:
        return acts
    if key == "partner":
        return acts[acts["delivery_type"] == "partner"]
    if key == "training":
        # The user asked specifically whether trainings linked to SSA
        # interventions improve those scores. Unlinked legacy training rows do
        # not enter this dosage; they remain visible as a data-quality gap.
        return acts[
            (acts["kind"] == "training") & acts["focus"].map(lambda focus: bool(focus))
        ]
    if key == "staff":
        return acts[acts["delivery_type"] == "staff"]
    if key == "cluster_meeting":
        return acts[acts["activity_type"].isin(CLUSTER_MEETING_TYPES)]
    if key == "special_project":
        return acts[acts["is_special_project"]]
    return acts.iloc[0:0]


def _correlation_strength(rho: float | None) -> str:
    if rho is None:
        return "not estimable"
    magnitude = abs(rho)
    if magnitude < 0.10:
        return "negligible"
    if magnitude < 0.30:
        return "weak"
    if magnitude < 0.50:
        return "moderate"
    if magnitude < 0.70:
        return "strong"
    return "very strong"


def _driver_association(
    imp: pd.DataFrame,
    acts: pd.DataFrame,
    key: str,
    label: str,
    description: str,
) -> dict:
    outcomes = (
        _school_outcomes(imp)
        if not imp.empty
        else pd.DataFrame(columns=["school_id", "mean_delta"])
    )
    selected = _driver_activity_rows(acts, key)
    counts = (
        selected.groupby("school_id").size().rename("dosage").reset_index()
        if not selected.empty
        else pd.DataFrame(columns=["school_id", "dosage"])
    )
    merged = outcomes.merge(counts, on="school_id", how="left")
    merged["dosage"] = merged["dosage"].fillna(0).astype(int)
    correlation = _spearman(merged["dosage"], merged["mean_delta"])
    exposed = merged[merged["dosage"] > 0]["mean_delta"]
    unexposed = merged[merged["dosage"] == 0]["mean_delta"]

    def _summary(series: pd.Series) -> tuple[float | None, float | None]:
        if series.empty:
            return None, None
        return round(float(series.mean()), 2), round(float(series.median()), 2)

    exposed_mean, exposed_median = _summary(exposed)
    unexposed_mean, unexposed_median = _summary(unexposed)
    return {
        "key": key,
        "label": label,
        "description": description,
        "correlation": correlation,
        "strength": _correlation_strength(correlation["rho"]),
        "activities": int(selected["activity_id"].nunique())
        if not selected.empty
        else 0,
        "schools_exposed": int(len(exposed)),
        "schools_unexposed": int(len(unexposed)),
        "exposed_mean_delta": exposed_mean,
        "exposed_median_delta": exposed_median,
        "unexposed_mean_delta": unexposed_mean,
        "unexposed_median_delta": unexposed_median,
    }


def programme_driver_associations(imp: pd.DataFrame, acts: pd.DataFrame) -> list[dict]:
    """Five pre-declared Spearman tests with a family-wise correction.

    The families overlap by design (a partner-delivered training is both a
    partner exposure and a training exposure), so they are explanatory lenses,
    never additive shares of improvement.
    """
    rows = [
        _driver_association(imp, acts, key, label, description)
        for key, label, description in DRIVER_DEFINITIONS
    ]
    tests_run = len(DRIVER_DEFINITIONS)
    for row in rows:
        corr = row["correlation"]
        raw_p = corr["p"]
        adjusted = min(1.0, raw_p * tests_run) if raw_p is not None else None
        corr["p_adjusted"] = round(adjusted, 4) if adjusted is not None else None
        corr["tests_run"] = tests_run
        corr["raw_verdict"] = corr["verdict"]
        corr["verdict"] = _verdict(adjusted)
        rho = corr["rho"]
        if rho is None:
            row["signal"] = "Insufficient paired data"
        elif corr["verdict"] in ("significant", "suggestive") and rho > 0:
            row["signal"] = "Positive association"
        elif corr["verdict"] in ("significant", "suggestive") and rho < 0:
            row["signal"] = "Negative association"
        else:
            row["signal"] = "No reliable association detected"
    return rows


def funding_impact(
    imp: pd.DataFrame,
    acts: pd.DataFrame,
    school_names: dict[str, str],
    show_names: bool,
) -> dict:
    outcomes = _school_outcomes(imp)
    spend = (
        acts.groupby("school_id")["accepted_spend"].sum().rename("spend").reset_index()
        if not acts.empty
        else pd.DataFrame(columns=["school_id", "spend"])
    )
    merged = outcomes.merge(spend, on="school_id", how="left")
    merged["spend"] = merged["spend"].fillna(0.0)

    corr = _spearman(merged["spend"], merged["mean_delta"])

    funded = merged[merged["spend"] > 0]
    total_spend = float(merged["spend"].sum())
    improved_funded = funded[funded["mean_delta"] > IMPROVEMENT_THRESHOLD]
    net_points = float(funded["mean_delta"].sum()) if not funded.empty else 0.0

    quadrants = {
        "efficient": [],
        "high_cost": [],
        "low_spend_improved": [],
        "stalled": [],
    }
    if len(funded) >= 4:
        spend_median = float(funded["spend"].median())
        for _, row in funded.iterrows():
            improved = row["mean_delta"] > IMPROVEMENT_THRESHOLD
            high_spend = row["spend"] > spend_median
            key = (
                "high_cost"
                if high_spend and not improved
                else "efficient"
                if high_spend
                else "stalled"
                if not improved
                else "low_spend_improved"
            )
            quadrants[key].append(
                {
                    "school": school_names.get(row["school_id"], "School")
                    if show_names
                    else "(school withheld)",
                    "spend": int(row["spend"]),
                    "delta": round(float(row["mean_delta"]), 2),
                }
            )
        for key in quadrants:
            quadrants[key].sort(key=lambda r: -r["spend"])
            quadrants[key] = quadrants[key][:8]

    scatter = [
        [int(row["spend"]), round(float(row["mean_delta"]), 2)]
        for _, row in funded.iterrows()
    ]

    return {
        "correlation": corr,
        "total_accepted_spend": int(total_spend),
        "funded_schools": int(len(funded)),
        "funded_improved": int(len(improved_funded)),
        "ugx_per_improved_school": int(total_spend / len(improved_funded))
        if len(improved_funded)
        else None,
        "ugx_per_point": int(total_spend / net_points) if net_points > 0 else None,
        "net_points": round(net_points, 2),
        "quadrants": quadrants,
        "scatter": scatter,
    }


def target_achievement_link(imp: pd.DataFrame, fy: str) -> dict:
    """Do staff who hit their targets support improving schools? School-level
    mean assigned-staff achievement % vs school mean delta."""
    outcomes = _school_outcomes(imp)
    if outcomes.empty:
        return {
            "correlation": {
                "rho": None,
                "p": None,
                "n": 0,
                "verdict": "insufficient data",
            },
            "staff_evaluated": 0,
        }
    school_ids = list(outcomes["school_id"])
    links = list(
        StaffSchoolAssignment.objects.filter(school_id__in=school_ids)
        .select_related("staff__user")
        .values("school_id", "staff__user__id")
    )
    users_by_school: dict[str, set[str]] = defaultdict(set)
    for link in links:
        if link["staff__user__id"]:
            users_by_school[link["school_id"]].add(link["staff__user__id"])
    all_user_ids = sorted({u for us in users_by_school.values() for u in us})
    if not all_user_ids:
        return {
            "correlation": {
                "rho": None,
                "p": None,
                "n": 0,
                "verdict": "insufficient data",
            },
            "staff_evaluated": 0,
        }

    from apps.accounts.models import User

    users = list(User.objects.filter(id__in=all_user_ids, is_active=True))
    areas = active_target_areas()
    per_user = per_user_monthly_series(users, fy, areas)
    months = list(range(1, 13))
    pct_by_user: dict[str, float] = {}
    for user in users:
        targets, achieved = per_user[user.id]
        pct, _, total_target = weighted_period_pct(areas, targets, achieved, months)
        if total_target > 0:
            pct_by_user[user.id] = float(pct)

    rows = []
    for _, row in outcomes.iterrows():
        pcts = [
            pct_by_user[u]
            for u in users_by_school.get(row["school_id"], ())
            if u in pct_by_user
        ]
        if pcts:
            rows.append(
                {"achievement": sum(pcts) / len(pcts), "mean_delta": row["mean_delta"]}
            )
    frame = pd.DataFrame(rows)
    corr = (
        _spearman(frame["achievement"], frame["mean_delta"])
        if not frame.empty
        else {"rho": None, "p": None, "n": 0, "verdict": "insufficient data"}
    )
    return {"correlation": corr, "staff_evaluated": len(pct_by_user)}


def geographic_performance(imp: pd.DataFrame, districts: dict[str, str]) -> dict:
    """District × intervention median deltas + Kruskal-Wallis per intervention
    across districts with enough paired schools."""
    if imp.empty:
        return {"matrix": [], "tests": [], "lagging": []}
    frame = imp.copy()
    frame["district"] = frame["school_id"].map(districts)
    frame = frame[frame["district"].notna()]

    eligible = [
        d
        for d, grp in frame.groupby("district")
        if grp["school_id"].nunique() >= MIN_GROUP_N
    ]

    # One pass over the frame, then look everything up.
    #
    # This function used to filter the whole frame with a fresh boolean mask
    # for every (district, intervention) cell — once for the matrix, again to
    # assemble the Kruskal-Wallis groups, and a third time for the lagging
    # list, with the median recomputed twice per lagging cell. That is roughly
    # 24 full scans per district, and it made /impact a TWELVE SECOND page of
    # which only ~1s was the database. Grouping once is the same arithmetic on
    # the same rows: identical medians, identical group membership.
    by_cell = {
        key: series.to_numpy()
        for key, series in frame.groupby(["district", "intervention"])["delta"]
    }

    def _deltas(district: str, intervention: str):
        return by_cell.get((district, intervention), _EMPTY_DELTAS)

    matrix_rows = []
    for district in sorted(eligible):
        cells = []
        for intervention in ALL_INTERVENTIONS:
            deltas = _deltas(district, intervention)
            cells.append(
                {
                    "x": INTERVENTION_LABELS[intervention],
                    "y": round(float(np.median(deltas)), 2) if len(deltas) else None,
                }
            )
        matrix_rows.append({"name": district, "data": cells})

    tests = []
    lagging = []
    for intervention in ALL_INTERVENTIONS:
        groups = [_deltas(d, intervention) for d in eligible]
        groups = [g for g in groups if len(g) >= MIN_GROUP_N]
        entry = {
            "key": intervention,
            "label": INTERVENTION_LABELS[intervention],
            "districts_compared": len(groups),
        }
        if len(groups) < 2:
            entry.update({"p": None, "verdict": "insufficient data"})
        else:
            try:
                # scipy emits RuntimeWarning (rather than consistently raising
                # ValueError) for all-tied samples. Such data cannot support an
                # inference, so expose the existing honest "insufficient data"
                # outcome instead of leaking a warning into a request/test run.
                with warnings.catch_warnings():
                    warnings.simplefilter("error", RuntimeWarning)
                    _, p = stats.kruskal(*groups)
            except (RuntimeWarning, ValueError):  # all-identical values
                p = float("nan")
            if np.isnan(p):
                entry.update({"p": None, "verdict": "insufficient data"})
            else:
                entry.update({"p": round(float(p), 4), "verdict": _verdict(float(p))})
        tests.append(entry)

        for district in eligible:
            deltas = _deltas(district, intervention)
            if len(deltas) < MIN_GROUP_N:
                continue
            median = float(np.median(deltas))
            if median < DECLINE_THRESHOLD:
                lagging.append(
                    {
                        "district": district,
                        "intervention": INTERVENTION_LABELS[intervention],
                        "median_delta": round(median, 2),
                        "n": int(len(deltas)),
                    }
                )
    lagging.sort(key=lambda r: r["median_delta"])
    return {"matrix": matrix_rows, "tests": tests, "lagging": lagging[:10]}


def field_reality_overlay(principal, imp: pd.DataFrame, fy: str) -> list[dict]:
    """For every intervention: the measured direction plus what the field
    debriefs report. Interventions that are stuck get their top challenge
    types — the 'why is this not improving' panel."""
    debriefs = FieldDebriefService.scoped_queryset(principal, {"fy": fy}).filter(
        is_restricted_incident=False
    )
    tagged = list(debriefs.values("id", "intervention_tags", "risk_level"))
    by_intervention: dict[str, list[dict]] = defaultdict(list)
    for row in tagged:
        for tag in row["intervention_tags"] or []:
            by_intervention[tag].append(row)

    debrief_ids = [r["id"] for r in tagged]
    challenge_rows = list(
        DailyDebriefChallenge.objects.filter(debrief_id__in=debrief_ids).values(
            "debrief_id", "challenge_type"
        )
    )
    challenges_by_debrief: dict[str, list[str]] = defaultdict(list)
    for row in challenge_rows:
        challenges_by_debrief[row["debrief_id"]].append(row["challenge_type"])
    challenge_labels = dict(
        DailyDebriefChallenge._meta.get_field("challenge_type").choices
    )

    overlay = []
    for intervention in ALL_INTERVENTIONS:
        deltas = imp[imp["intervention"] == intervention]["delta"]
        median = round(float(deltas.median()), 2) if len(deltas) else None
        if median is None:
            direction = "no data"
        elif median > IMPROVEMENT_THRESHOLD:
            direction = "improving"
        elif median < DECLINE_THRESHOLD:
            direction = "declining"
        else:
            direction = "stagnant"

        rows = by_intervention.get(intervention, [])
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            for ctype in challenges_by_debrief.get(row["id"], []):
                counts[ctype] += 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
        overlay.append(
            {
                "key": intervention,
                "label": INTERVENTION_LABELS[intervention],
                "median_delta": median,
                "n_schools": int(deltas.shape[0]),
                "direction": direction,
                "debriefs": len(rows),
                "critical_debriefs": sum(
                    1 for r in rows if r["risk_level"] == "critical"
                ),
                "top_challenges": [
                    {"label": str(challenge_labels.get(k, k)), "count": int(v)}
                    for k, v in top
                ],
            }
        )
    overlay.sort(key=lambda r: (r["median_delta"] is None, r["median_delta"] or 0))
    return overlay


# ── Dashboard assembly ────────────────────────────────────────────────────────


def _fy_from_query(query: dict) -> str:
    fy = str(query.get("fy") or "")
    return fy if fy in set(fy_options()) else get_operational_fy()


def _fy_option_list(selected_fy: str) -> list[dict]:
    values = sorted(
        set(fy_options()) | {selected_fy}, key=lambda value: int(value), reverse=True
    )
    return [{"value": value, "label": f"FY {value}"} for value in values]


def _ugx(value: int | None) -> str | None:
    return f"UGX {value:,}" if value is not None else None


def _school_group_metadata(school_rows: list[dict]) -> dict[str, dict[str, str]]:
    """Resolve every grouping label in a bounded set of bulk queries."""
    from apps.accounts.models import (
        StaffProfile,
        StaffSchoolAssignment,
        StaffSupervisorAssignment,
    )
    from apps.core.rbac import EdifyRole
    from apps.clusters.models import Cluster

    cluster_ids = {row["cluster_id"] for row in school_rows if row["cluster_id"]}
    cluster_names = dict(
        Cluster.objects.filter(id__in=cluster_ids).values_list("id", "name")
    )

    school_ids = [row["id"] for row in school_rows]
    assignment_owners: dict[str, str] = {}
    for link in StaffSchoolAssignment.objects.filter(
        school_id__in=school_ids,
        staff__deleted_at__isnull=True,
    ).values("school_id", "staff_id", "staff__user__active_role"):
        current = assignment_owners.get(link["school_id"])
        # Prefer the operational CCEO assignment when legacy data contains
        # multiple links; otherwise retain the first deterministic owner.
        if current is None or link["staff__user__active_role"] == EdifyRole.CCEO.value:
            assignment_owners[link["school_id"]] = link["staff_id"]
    effective_owner = {
        row["id"]: row["account_owner_id"] or assignment_owners.get(row["id"])
        for row in school_rows
    }
    owner_ids = {owner_id for owner_id in effective_owner.values() if owner_id}
    owners = {
        row["id"]: row
        for row in StaffProfile.objects.filter(id__in=owner_ids)
        .select_related("user")
        .values("id", "user__name", "user__active_role")
    }
    supervisor_names = {
        row["supervisee_id"]: row["supervisor__user__name"]
        for row in StaffSupervisorAssignment.objects.filter(
            supervisee_id__in=owner_ids,
            supervisor__deleted_at__isnull=True,
            supervisor__user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        ).values("supervisee_id", "supervisor__user__name")
    }

    metadata: dict[str, dict[str, str]] = {}
    for row in school_rows:
        owner_id = effective_owner.get(row["id"])
        owner = owners.get(owner_id, {})
        if owner.get("user__active_role") == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
            pl_name = owner.get("user__name") or "Unassigned Program Lead"
        else:
            pl_name = supervisor_names.get(owner_id, "Unassigned Program Lead")
        metadata[row["id"]] = {
            "pl": pl_name,
            "sub_region": row["district__sub_region__name"] or "Unassigned sub-region",
            "district": row["district__name"] or "Unassigned district",
            "cluster": cluster_names.get(row["cluster_id"], "Unassigned cluster"),
            "sub_county": row["sub_county__name"] or "Unassigned sub-county",
            "parish": row["parish__name"] or "Unassigned parish",
        }
    return metadata


def _group_options(metadata: dict[str, dict[str, str]], selected: str) -> list[dict]:
    keys = ["pl", "sub_region", "district", "cluster", "sub_county"]
    parish_populated = any(
        values["parish"] != "Unassigned parish" for values in metadata.values()
    )
    if parish_populated:
        keys.append("parish")
    return [
        {
            "value": key,
            "label": GROUP_LABELS[key],
            "selected": key == selected,
        }
        for key in keys
    ]


def grouped_driver_associations(
    imp: pd.DataFrame,
    acts: pd.DataFrame,
    metadata: dict[str, dict[str, str]],
    group_by: str,
    *,
    page: int | None = None,
    page_size: int = 20,
) -> list[dict] | dict:
    if imp.empty:
        empty = []
        if page is None:
            return empty
        return {
            "rows": empty,
            "page": 1,
            "page_size": page_size,
            "total": 0,
            "total_pages": 1,
            "has_previous": False,
            "has_next": False,
            "previous_page": None,
            "next_page": None,
        }
    labels = {school_id: values[group_by] for school_id, values in metadata.items()}
    frame = imp.copy()
    frame["group_label"] = (
        frame["school_id"]
        .map(labels)
        .fillna(f"Unassigned {GROUP_LABELS[group_by].lower()}")
    )
    activity_rows = acts.copy()
    if not activity_rows.empty:
        activity_rows["group_label"] = (
            activity_rows["school_id"]
            .map(labels)
            .fillna(f"Unassigned {GROUP_LABELS[group_by].lower()}")
        )

    prepared = []
    for group_label, group_imp in frame.groupby("group_label", sort=True):
        group_acts = (
            activity_rows[activity_rows["group_label"] == group_label]
            if not activity_rows.empty
            else activity_rows
        )
        outcomes = _school_outcomes(group_imp)
        prepared.append(
            {
                "name": str(group_label),
                "paired_schools": int(outcomes["school_id"].nunique()),
                "median_delta": round(float(outcomes["mean_delta"].median()), 2),
                "mean_delta": round(float(outcomes["mean_delta"].mean()), 2),
                "improved_pct": round(
                    float(
                        (outcomes["mean_delta"] > IMPROVEMENT_THRESHOLD).mean() * 100
                    ),
                    1,
                ),
                "_imp": group_imp,
                "_acts": group_acts,
            }
        )
    # Leadership sees attention-first ordering; alphabetical is the stable
    # tie-break for equal medians.
    prepared.sort(key=lambda row: (row["median_delta"], row["name"]))
    total = len(prepared)
    total_pages = max(1, int(np.ceil(total / page_size)))
    current_page = min(max(1, int(page or 1)), total_pages)
    visible = prepared
    if page is not None:
        start = (current_page - 1) * page_size
        visible = prepared[start : start + page_size]

    rows = []
    for row in visible:
        group_imp = row.pop("_imp")
        group_acts = row.pop("_acts")
        row["drivers"] = programme_driver_associations(group_imp, group_acts)
        rows.append(row)
    if page is None:
        return rows
    return {
        "rows": rows,
        "page": current_page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_previous": current_page > 1,
        "has_next": current_page < total_pages,
        "previous_page": current_page - 1 if current_page > 1 else None,
        "next_page": current_page + 1 if current_page < total_pages else None,
    }


def build_dashboard(principal, query: dict) -> dict:
    fy = _fy_from_query(query)
    prev_fy = str(int(fy) - 1)
    schools_qs, scope = _scoped_schools(principal)
    school_rows = list(
        schools_qs.values(
            "id",
            "name",
            "district__name",
            "district__sub_region__name",
            "sub_county__name",
            "parish__name",
            "cluster_id",
            "account_owner_id",
        )
    )
    school_ids = [row["id"] for row in school_rows]
    school_names = {row["id"]: row["name"] for row in school_rows}
    districts = {row["id"]: row["district__name"] for row in school_rows}
    show_names = bool(getattr(scope, "can_view_school_level_detail", True))

    imp = improvement_frame(school_ids, fy)
    acts = activity_frame(imp, school_ids)
    paired = int(imp["school_id"].nunique()) if not imp.empty else 0

    outcomes = _school_outcomes(imp) if not imp.empty else pd.DataFrame()
    median_delta = (
        round(float(outcomes["mean_delta"].median()), 2) if not outcomes.empty else None
    )
    improved_pct = (
        round(float((outcomes["mean_delta"] > IMPROVEMENT_THRESHOLD).mean() * 100), 1)
        if not outcomes.empty
        else None
    )
    outcome_summary = describe_numeric(
        outcomes["mean_delta"].tolist() if not outcomes.empty else [],
        target=IMPROVEMENT_THRESHOLD,
    )

    visits = dosage_impact(imp, acts, "visit")
    trainings = dosage_impact(imp, acts, "training")
    drivers = programme_driver_associations(imp, acts)
    funding = funding_impact(imp, acts, school_names, show_names)
    targets = target_achievement_link(imp, fy)
    geography = geographic_performance(imp, districts)
    field_reality = field_reality_overlay(principal, imp, fy)
    group_metadata = _school_group_metadata(school_rows)
    available_group_keys = {
        option["value"] for option in _group_options(group_metadata, "")
    }
    default_group = (
        "pl"
        if getattr(principal, "active_role", "") in COUNTRY_DRIVER_ROLES
        else "district"
    )
    requested_group = str(query.get("group_by") or default_group)
    group_by = (
        requested_group if requested_group in available_group_keys else default_group
    )
    if group_by not in available_group_keys:
        group_by = "district"
    try:
        group_page = max(1, int(query.get("group_page") or 1))
    except (TypeError, ValueError):
        group_page = 1
    grouped_result = grouped_driver_associations(
        imp,
        acts,
        group_metadata,
        group_by,
        page=group_page,
        page_size=20,
    )
    all_training_rows = _driver_activity_rows(acts, "training")
    all_trainings = acts[acts["kind"] == "training"] if not acts.empty else acts

    return {
        "filters": {
            "fy": fy,
            "fy_label": f"FY {fy}",
            "prev_fy": prev_fy,
            "fy_options": _fy_option_list(fy),
            "group_by": group_by,
            "group_by_label": GROUP_LABELS[group_by],
            "group_options": _group_options(group_metadata, group_by),
        },
        "scope": {
            "role": getattr(scope, "active_role", ""),
            "can_view_school_details": show_names,
        },
        "coverage": {
            "schools_in_scope": len(school_ids),
            "schools_paired": paired,
            "activities_in_window": int(acts["activity_id"].nunique())
            if not acts.empty
            else 0,
            "trainings_in_window": int(all_trainings["activity_id"].nunique())
            if not all_trainings.empty
            else 0,
            "ssa_linked_trainings": int(all_training_rows["activity_id"].nunique())
            if not all_training_rows.empty
            else 0,
        },
        "kpis": {
            "median_delta": median_delta,
            "improved_pct": improved_pct,
            "total_accepted_spend_value": funding["total_accepted_spend"],
            "total_accepted_spend": _ugx(funding["total_accepted_spend"]),
            "ugx_per_point": _ugx(funding["ugx_per_point"]),
        },
        "analytics": {
            "outcomes": outcome_summary,
            "engine": engine_metadata(
                "impact", record_count=paired, confirmed_only=True
            ),
        },
        "methodology": {
            "minimum_group_n": MIN_GROUP_N,
            "minimum_correlation_n": MIN_CORR_N,
            "driver_tests": len(DRIVER_DEFINITIONS),
            "p_adjustment": "Bonferroni",
        },
        "visits": visits,
        "trainings": trainings,
        "drivers": drivers,
        "grouped_drivers": grouped_result["rows"],
        "grouped_driver_pagination": grouped_result,
        "funding": funding,
        "targets": targets,
        "geography": geography,
        "field_reality": field_reality,
        # Chart payloads are JSON-encoded here (not repr'd in the template)
        # so None becomes null and the embedded literals are valid JS.
        "charts": {
            "bucket_labels": json.dumps([b["label"] for b in visits["buckets"]]),
            "visit_bucket_medians": json.dumps(
                [
                    b["median_delta"] if b["median_delta"] is not None else 0
                    for b in visits["buckets"]
                ]
            ),
            "training_bucket_medians": json.dumps(
                [
                    b["median_delta"] if b["median_delta"] is not None else 0
                    for b in trainings["buckets"]
                ]
            ),
            "funding_scatter": json.dumps(funding["scatter"]),
            "geo_heatmap": json.dumps(geography["matrix"]),
        },
        "method_notes": [
            f"Improvement = confirmed SSA score in FY {fy} minus confirmed SSA score in FY {prev_fy}, per school per intervention. Only schools assessed in both cycles are analysed ({paired} of {len(school_ids)} in scope).",
            "Dosage counts only verified/completed activities dated inside each school's own exposure window (between its two assessments); recorded delivery date is preferred over the planned date.",
            "Training dosage includes only training records linked to at least one SSA intervention. The focused-training table then compares intervention-specific score movement among schools that started weak.",
            "Partner, training, staff, cluster-meeting and special-project families can overlap (for example, a partner-delivered training appears in two lenses), so the five correlations are not additive shares of improvement.",
            "The five driver p-values use a Bonferroni family-wise correction. Cards show Spearman rho with an approximate 95% confidence interval, adjusted p-value, and the paired-school sample size.",
            f"Treated-vs-untreated comparisons are restricted to schools with a weak initial SSA score (below {WEAK_BASELINE}) on that intervention, because activity planning already targets weak interventions — comparing against strong schools would only measure regression to the mean.",
            "Spend counts accountant-accepted money only (accounted advances and partner payments, plain UGX). Cluster activities split spend equally across attended schools.",
            f"Rank-based tests (Spearman, Mann-Whitney, Kruskal-Wallis); groups under {MIN_GROUP_N} schools and correlations under {MIN_CORR_N} schools report 'insufficient data' rather than an unreliable number. Correlation is not causation — confounding, reverse causation and targeted support remain possible, so these results direct attention rather than prove attribution.",
        ],
    }
