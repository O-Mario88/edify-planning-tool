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
from scipy import stats

from apps.accounts.models import StaffSchoolAssignment
from apps.activities.models import Activity
from apps.analytics.decision_engine import (
    DECLINE_THRESHOLD,
    IMPROVEMENT_THRESHOLD,
)
from apps.analytics.pl_analytics_service import (
    COMPLETED_STATUSES,
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


# ── Scope (same shape as ssa_performance_service — correct RVP handling) ─────


def _scoped_schools(principal):
    """RVP may aggregate over assigned regions but never see school identity;
    other roles follow the shared scope service exactly."""
    from apps.core.scoping import scoped_school_queryset

    scope = resolve_user_scope(principal)
    schools = School.objects.filter(deleted_at__isnull=True)
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
    Columns: activity_id, school_id, kind, planned_date, focus (set),
    n_attributed, accepted_spend (UGX share)."""
    if imp.empty:
        return pd.DataFrame(
            columns=[
                "activity_id",
                "school_id",
                "kind",
                "planned_date",
                "focus",
                "accepted_spend",
            ]
        )
    windows = (
        imp.groupby("school_id")[["window_start", "window_end"]]
        .first()
        .to_dict("index")
    )
    lo = min(w["window_start"] for w in windows.values())
    hi = max(w["window_end"] for w in windows.values())

    activities = list(
        Activity.objects.filter(
            Q(school_id__in=school_ids) | Q(attended_school_ids__overlap=school_ids),
            deleted_at__isnull=True,
            status__in=COMPLETED_STATUSES,
            planned_date__isnull=False,
            planned_date__gt=lo,
            planned_date__lte=hi,
        ).values(
            "id",
            "school_id",
            "activity_type",
            "focus_intervention",
            "purpose_intervention",
            "secondary_focus_interventions",
            "planned_date",
            "attended_school_ids",
        )
    )
    if not activities:
        return pd.DataFrame(
            columns=[
                "activity_id",
                "school_id",
                "kind",
                "planned_date",
                "focus",
                "accepted_spend",
            ]
        )

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
        attributed = (
            [act["school_id"]]
            if act["school_id"]
            else [s for s in (act["attended_school_ids"] or []) if s in scoped]
        )
        attributed = [
            s
            for s in attributed
            if s in windows
            and windows[s]["window_start"]
            < act["planned_date"]
            <= windows[s]["window_end"]
        ]
        if not attributed:
            continue
        share = spend.get(act["id"], 0) / len(attributed)
        focus = _activity_focus_set(act)
        for sid in attributed:
            rows.append(
                {
                    "activity_id": act["id"],
                    "school_id": sid,
                    "kind": kind,
                    "planned_date": act["planned_date"],
                    "focus": focus,
                    "accepted_spend": share,
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "activity_id",
            "school_id",
            "kind",
            "planned_date",
            "focus",
            "accepted_spend",
        ],
    )


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
        return {"rho": None, "p": None, "n": n, "verdict": "insufficient data"}
    rho, p = stats.spearmanr(x, y)
    if np.isnan(rho):
        return {"rho": None, "p": None, "n": n, "verdict": "insufficient data"}
    return {
        "rho": round(float(rho), 3),
        "p": round(float(p), 4),
        "n": n,
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
    matrix_rows = []
    for district in sorted(eligible):
        cells = []
        d_frame = frame[frame["district"] == district]
        for intervention in ALL_INTERVENTIONS:
            deltas = d_frame[d_frame["intervention"] == intervention]["delta"]
            cells.append(
                {
                    "x": INTERVENTION_LABELS[intervention],
                    "y": round(float(deltas.median()), 2) if len(deltas) else None,
                }
            )
        matrix_rows.append({"name": district, "data": cells})

    tests = []
    lagging = []
    for intervention in ALL_INTERVENTIONS:
        groups = [
            frame[(frame["district"] == d) & (frame["intervention"] == intervention)][
                "delta"
            ].to_numpy()
            for d in eligible
        ]
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

        i_frame = frame[frame["intervention"] == intervention]
        for district in eligible:
            deltas = i_frame[i_frame["district"] == district]["delta"]
            if (
                len(deltas) >= MIN_GROUP_N
                and float(deltas.median()) < DECLINE_THRESHOLD
            ):
                lagging.append(
                    {
                        "district": district,
                        "intervention": INTERVENTION_LABELS[intervention],
                        "median_delta": round(float(deltas.median()), 2),
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


def build_dashboard(principal, query: dict) -> dict:
    fy = _fy_from_query(query)
    prev_fy = str(int(fy) - 1)
    schools_qs, scope = _scoped_schools(principal)
    school_rows = list(schools_qs.values("id", "name", "district__name"))
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
    funding = funding_impact(imp, acts, school_names, show_names)
    targets = target_achievement_link(imp, fy)
    geography = geographic_performance(imp, districts)
    field_reality = field_reality_overlay(principal, imp, fy)

    return {
        "filters": {
            "fy": fy,
            "fy_label": f"FY {fy}",
            "prev_fy": prev_fy,
            "fy_options": _fy_option_list(fy),
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
        },
        "kpis": {
            "median_delta": median_delta,
            "improved_pct": improved_pct,
            "total_accepted_spend": _ugx(funding["total_accepted_spend"]),
            "ugx_per_point": _ugx(funding["ugx_per_point"]),
        },
        "analytics": {
            "outcomes": outcome_summary,
            "engine": engine_metadata(
                "impact", record_count=paired, confirmed_only=True
            ),
        },
        "visits": visits,
        "trainings": trainings,
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
            "Dosage counts only executed activities dated inside each school's own exposure window (between its two assessments).",
            f"Treated-vs-untreated comparisons are restricted to schools with a weak baseline (score below {WEAK_BASELINE}) on that intervention, because activity planning already targets weak interventions — comparing against strong schools would only measure regression to the mean.",
            "Spend counts accountant-accepted money only (accounted advances and partner payments, plain UGX). Cluster activities split spend equally across attended schools.",
            f"Rank-based tests (Spearman, Mann-Whitney, Kruskal-Wallis); groups under {MIN_GROUP_N} schools report 'insufficient data' rather than an unreliable number. Correlation is not causation — these results direct attention, they do not close questions.",
        ],
    }
