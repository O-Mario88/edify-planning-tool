"""School Visit Effectiveness — the ONE canonical service relating school
visits to verified SSA change (mandate: one shared analytics domain).

Methodology (v1) reproduces the defensible approach of the June-2026
"School Visit Analysis" study dynamically from live records — never from
the study's static numbers:

* Cohort: a school enters only with a VERIFIED baseline SSA in the baseline
  FY and a VERIFIED follow-up SSA in the follow-up FY (default FY2024 →
  FY2026; FY2025 is excluded by the methodology because the assessment-cycle
  change broke comparability). Latest confirmed record per school per FY.
* Visits: only visit-type activities at the school dated AFTER the school's
  baseline assessment and ON/BEFORE its follow-up assessment. Cancelled,
  deferred, rejected and soft-deleted work never counts. "Delivered" means
  the canonical completion chain (apps.core.activity_types.
  COMPLETED_WORK_STATUSES) — a scheduled visit is not a delivered visit.
* Separation is never blurred: Core vs Client, staff vs Partner delivery,
  and visit purpose are first-class dimensions.
* Recommendation alignment: a visit counts as aligned when its focus
  interventions intersect the school's two weakest verified baseline
  interventions — the reproducible stand-in for "addressed an active SSA
  recommendation" (no persisted recommendation record exists).
* Language: associations only. r/p come from scipy; every group carries its
  sample size; small samples are flagged, never hidden. No output of this
  module may be phrased as causation, and none of it is a staff rating.

Serving pattern mirrors apps.analytics.impact_engine: ORM .values() →
pandas, min-N guards, JSON-string chart payloads, method notes, and role
scope through resolve_user_scope / scoped_school_queryset (school-level
detail redacted when the scope says so).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd
from scipy import stats

from apps.core.activity_types import COMPLETED_WORK_STATUSES, VISIT_TYPES
from apps.core.enums import SsaIntervention
from apps.core.scoping import resolve_user_scope, scoped_school_queryset

METHODOLOGY_VERSION = "v1-fy24-fy26"
DEFAULT_BASELINE_FY = "2024"
DEFAULT_FOLLOWUP_FY = "2026"
# FY2025 assessments were excluded by the source methodology: the assessment
# cycle changed and some schools repeated assessments, breaking comparability.
EXCLUDED_ASSESSMENT_FYS = ("2025",)

MIN_GROUP_N = 8
MIN_CORR_N = 10
SIGNIFICANT_P = 0.05

INTERVENTIONS = [c[0] for c in SsaIntervention.choices]
INTERVENTION_LABELS = dict(SsaIntervention.choices)

# Historical display labels (the study's wording) → canonical keys. Display
# metadata only — one canonical key is ever stored (mandate §4).
LEGACY_INTERVENTION_LABELS = {
    "Christ-like Behavior": SsaIntervention.CHRISTLIKE_BEHAVIOUR,
    "Exposure to the Word of God": SsaIntervention.EXPOSURE_TO_WORD_OF_GOD,
    "Fees/Budget/Accounts": SsaIntervention.FINANCIAL_HEALTH,
    "Leadership Best Practice": SsaIntervention.LEADERSHIP,
    "Government Requirements": SsaIntervention.GOVERNMENT_REQUIREMENT,
    "Learning Environment": SsaIntervention.LEARNING_ENVIRONMENT,
    "Teaching Environment": SsaIntervention.TEACHING_ENVIRONMENT,
    "Enrollment": SsaIntervention.ENROLMENT,
}

# Visit-purpose buckets derived from the canonical activity type. Purpose is
# a first-class dimension: a data-collection call is not a coaching call.
PURPOSE_BY_TYPE = {
    "baseline_ssa_visit": "data_collection",
    "school_visit_ssa_collection": "data_collection",
    "partner_ssa_collection": "data_collection",
    "core_assessment_visit": "data_collection",
    "coaching_visit": "coaching",
    "in_school_coaching_visit": "coaching",
    "follow_up_visit": "intervention_follow_up",
    "training_follow_up_visit": "intervention_follow_up",
    "school_visit": "school_support",
    "in_school_support": "school_support",
    "core_visit": "school_support",
    "donor_visit": "other",
    "story_gathering_visit": "other",
    "school_invitation": "other",
    "social_visit": "other",
}
PURPOSE_LABELS = {
    "data_collection": "SSA / data collection",
    "coaching": "Coaching",
    "intervention_follow_up": "Intervention follow-up",
    "school_support": "School support",
    "other": "Other authorised",
}

EXCLUDED_VISIT_STATUSES = ("cancelled", "deferred", "rejected", "not_planned")


def _verdict(p: float | None, n: int) -> str:
    if n < MIN_CORR_N:
        return "insufficient sample"
    if p is None:
        return "not computable"
    if p <= SIGNIFICANT_P:
        return "statistically significant association"
    return "no significant association"


@dataclass
class Cohort:
    """The comparable-school frame plus its exclusions ledger."""

    schools: pd.DataFrame  # one row per school: ids, type, geo, dates, avgs
    scores: pd.DataFrame  # school_id × intervention: base/follow/delta
    excluded: dict  # reason -> count
    baseline_fy: str
    followup_fy: str


class SchoolVisitEffectivenessAnalyticsService:
    """Every role page, export and report consumes THIS service."""

    # ── Cohort construction (mandate §3) ────────────────────────────────────
    @staticmethod
    def build_cohort(principal, baseline_fy=None, followup_fy=None) -> Cohort:
        from apps.ssa.models import SsaRecord, SsaScore

        baseline_fy = baseline_fy or DEFAULT_BASELINE_FY
        followup_fy = followup_fy or DEFAULT_FOLLOWUP_FY

        scope = resolve_user_scope(principal)
        schools_qs = scoped_school_queryset(scope).filter(deleted_at__isnull=True)
        schools = pd.DataFrame(
            schools_qs.values(
                "id", "name", "school_type", "district_id", "district__name",
                "region_id", "region__name", "district__sub_region__name",
            )
        )
        excluded: dict[str, int] = {}
        if schools.empty:
            return Cohort(schools, pd.DataFrame(), excluded, baseline_fy, followup_fy)

        ids = list(schools["id"])
        recs = pd.DataFrame(
            SsaRecord.objects.filter(
                school_id__in=ids,
                fy__in=[baseline_fy, followup_fy],
                verification_status="confirmed",
                deleted_at__isnull=True,
            )
            .order_by("school_id", "fy", "-date_of_ssa", "-created_at")
            .values("id", "school_id", "fy", "date_of_ssa", "average_score")
        )
        if recs.empty:
            excluded["no_verified_ssa"] = len(ids)
            return Cohort(
                schools.iloc[0:0], pd.DataFrame(), excluded, baseline_fy, followup_fy
            )

        # Latest confirmed record per school per FY (duplicates resolved by
        # recency, mirroring latest_applicable_record) — a school never
        # counts twice in a cohort.
        latest = recs.drop_duplicates(subset=["school_id", "fy"], keep="first")
        base = latest[latest["fy"] == baseline_fy].set_index("school_id")
        follow = latest[latest["fy"] == followup_fy].set_index("school_id")

        paired_ids = base.index.intersection(follow.index)
        excluded["missing_baseline_ssa"] = int(len(ids) - len(base))
        excluded["missing_followup_ssa"] = int(len(base.index.difference(follow.index)))

        schools = schools[schools["id"].isin(paired_ids)].copy()
        # dict-based lookups: pandas 3 Series.map(Series) refuses tz-datetime
        # casting on fill, and dicts sidestep the dtype inference entirely.
        schools["baseline_record_id"] = schools["id"].map(base["id"].to_dict())
        schools["followup_record_id"] = schools["id"].map(follow["id"].to_dict())
        schools["baseline_date"] = schools["id"].map(base["date_of_ssa"].to_dict())
        schools["followup_date"] = schools["id"].map(follow["date_of_ssa"].to_dict())
        schools["baseline_avg"] = schools["id"].map(base["average_score"].to_dict())
        schools["followup_avg"] = schools["id"].map(follow["average_score"].to_dict())
        schools["baseline_date"] = pd.to_datetime(schools["baseline_date"], utc=True)
        schools["followup_date"] = pd.to_datetime(schools["followup_date"], utc=True)
        schools["overall_delta"] = schools["followup_avg"] - schools["baseline_avg"]
        # An inverted window (data entry error) is not comparable.
        bad_window = schools["followup_date"] <= schools["baseline_date"]
        excluded["invalid_assessment_window"] = int(bad_window.sum())
        schools = schools[~bad_window]

        rec_ids = list(schools["baseline_record_id"]) + list(
            schools["followup_record_id"]
        )
        score_rows = pd.DataFrame(
            SsaScore.objects.filter(ssa_record_id__in=rec_ids).values(
                "ssa_record_id", "intervention", "score"
            )
        )
        scores = pd.DataFrame()
        if not score_rows.empty:
            by_rec = score_rows.set_index(["ssa_record_id", "intervention"])["score"]
            rows = []
            for _, s in schools.iterrows():
                for iv in INTERVENTIONS:
                    b = by_rec.get((s["baseline_record_id"], iv))
                    f = by_rec.get((s["followup_record_id"], iv))
                    rows.append(
                        {
                            "school_id": s["id"],
                            "intervention": iv,
                            "baseline": b,
                            "followup": f,
                            "delta": (f - b)
                            if (b is not None and f is not None)
                            else None,
                        }
                    )
            scores = pd.DataFrame(rows)
        return Cohort(schools, scores, excluded, baseline_fy, followup_fy)

    # ── Visit frame (mandate §3 window + §5 record) ─────────────────────────
    @staticmethod
    def visit_frame(cohort: Cohort) -> pd.DataFrame:
        from apps.activities.models import Activity

        if cohort.schools.empty:
            return pd.DataFrame()
        window = cohort.schools.set_index("id")[["baseline_date", "followup_date"]]
        visits = pd.DataFrame(
            Activity.objects.filter(
                school_id__in=list(window.index),
                activity_type__in=VISIT_TYPES,
                deleted_at__isnull=True,
            )
            .exclude(status__in=EXCLUDED_VISIT_STATUSES)
            .values(
                "id", "school_id", "activity_type", "status", "delivery_type",
                "assigned_partner_id", "responsible_staff_id", "scheduled_date",
                "planned_date", "focus_intervention", "purpose_intervention",
                "secondary_focus_interventions", "ia_verification_status",
                "evidence_status", "salesforce_activity_id",
            )
        )
        if visits.empty:
            return visits

        # Effective visit date: planned_date, else the scheduled timestamp's
        # date. Only visits strictly after baseline and on/before follow-up.
        sched = pd.to_datetime(visits["scheduled_date"], utc=True).dt.date
        planned = visits["planned_date"]
        visits["visit_date"] = planned.where(planned.notna(), sched)
        visits = visits[visits["visit_date"].notna()]
        b = visits["school_id"].map(window["baseline_date"].to_dict())
        f = visits["school_id"].map(window["followup_date"].to_dict())
        visits["baseline_date"] = pd.to_datetime(b, utc=True).dt.date
        visits["followup_date"] = pd.to_datetime(f, utc=True).dt.date
        visits = visits[
            (visits["visit_date"] > visits["baseline_date"])
            & (visits["visit_date"] <= visits["followup_date"])
        ].copy()

        visits["purpose"] = (
            visits["activity_type"].map(PURPOSE_BY_TYPE).fillna("other")
        )
        visits["executor"] = visits["delivery_type"].where(
            visits["delivery_type"].isin(["staff", "partner"]), "staff"
        )
        visits["delivered"] = visits["status"].isin(COMPLETED_WORK_STATUSES)
        visits["ia_cleared"] = visits["ia_verification_status"] == "confirmed"
        visits["has_salesforce"] = visits["salesforce_activity_id"].notna()
        visits["has_evidence"] = ~visits["evidence_status"].isin(
            [None, "", "none", "pending"]
        )
        return visits

    # ── Recommendation alignment (reproducible §7 rule) ─────────────────────
    @staticmethod
    def _alignment(cohort: Cohort, visits: pd.DataFrame) -> pd.DataFrame:
        """A visit is 'aligned' when a focus intervention intersects the
        school's two weakest verified BASELINE interventions."""
        if visits.empty or cohort.scores.empty:
            return visits.assign(aligned=pd.Series(dtype=bool))
        base = cohort.scores.dropna(subset=["baseline"])
        weakest = (
            base.sort_values(["school_id", "baseline"])
            .groupby("school_id")["intervention"]
            .apply(lambda s: set(s.head(2)))
        )

        def focus_set(row):
            out = set()
            for f in (row["focus_intervention"], row["purpose_intervention"]):
                if f:
                    out.add(f)
            out.update(row["secondary_focus_interventions"] or [])
            return out

        visits = visits.copy()
        visits["focus_set"] = visits.apply(focus_set, axis=1)
        visits["has_focus"] = visits["focus_set"].map(bool)
        visits["aligned"] = visits.apply(
            lambda r: bool(r["focus_set"] & weakest.get(r["school_id"], set())),
            axis=1,
        )
        return visits

    # ── The dashboard (every role consumes this) ────────────────────────────
    @staticmethod
    def build_dashboard(principal, query: dict | None = None) -> dict:
        query = query or {}
        scope = resolve_user_scope(principal)
        baseline_fy = query.get("baseline_fy") or DEFAULT_BASELINE_FY
        followup_fy = query.get("followup_fy") or DEFAULT_FOLLOWUP_FY
        if baseline_fy in EXCLUDED_ASSESSMENT_FYS or followup_fy in EXCLUDED_ASSESSMENT_FYS:
            baseline_fy, followup_fy = DEFAULT_BASELINE_FY, DEFAULT_FOLLOWUP_FY

        svc = SchoolVisitEffectivenessAnalyticsService
        cohort = svc.build_cohort(principal, baseline_fy, followup_fy)
        school_type = query.get("school_type")
        if school_type in ("core", "client") and not cohort.schools.empty:
            keep = cohort.schools["school_type"] == school_type
            cohort = Cohort(
                cohort.schools[keep],
                cohort.scores[
                    cohort.scores["school_id"].isin(cohort.schools[keep]["id"])
                ]
                if not cohort.scores.empty
                else cohort.scores,
                cohort.excluded,
                cohort.baseline_fy,
                cohort.followup_fy,
            )

        visits = svc.visit_frame(cohort)
        visits = svc._alignment(cohort, visits)
        delivered = visits[visits["delivered"]] if not visits.empty else visits

        n = int(len(cohort.schools))
        out: dict = {
            "methodology": {
                "version": METHODOLOGY_VERSION,
                "baseline_fy": f"FY{baseline_fy}",
                "followup_fy": f"FY{followup_fy}",
                "excluded_fys": [f"FY{x}" for x in EXCLUDED_ASSESSMENT_FYS],
                "min_group_n": MIN_GROUP_N,
                "min_corr_n": MIN_CORR_N,
            },
            "scope": {
                "role": getattr(principal, "active_role", ""),
                "can_view_school_details": bool(
                    getattr(scope, "can_view_school_level_detail", True)
                ),
            },
            "cohort": {
                "comparable_schools": n,
                "core": int((cohort.schools["school_type"] == "core").sum()) if n else 0,
                "client": int((cohort.schools["school_type"] == "client").sum()) if n else 0,
                "excluded": cohort.excluded,
                "sample_quality": (
                    "none" if n == 0 else "very limited" if n < MIN_GROUP_N
                    else "limited" if n < 30 else "adequate"
                ),
            },
        }
        if n == 0:
            out["charts"] = {}
            out["method_notes"] = svc._method_notes()
            return out

        # ── coverage + delivery ────────────────────────────────────────────
        visited_ids = set(delivered["school_id"]) if not delivered.empty else set()
        staff_v = delivered[delivered["executor"] == "staff"] if not delivered.empty else delivered
        partner_v = delivered[delivered["executor"] == "partner"] if not delivered.empty else delivered
        pdc = (
            partner_v[partner_v["purpose"] == "data_collection"]
            if not partner_v.empty
            else partner_v
        )
        out["coverage"] = {
            "schools_visited": len(visited_ids),
            "schools_not_visited": n - len(visited_ids),
            "delivered_visits": int(len(delivered)),
            "scheduled_only_visits": int(len(visits) - len(delivered)),
            "staff_visits": int(len(staff_v)),
            "partner_visits": int(len(partner_v)),
            "partner_data_collection_share": (
                round(len(pdc) / len(partner_v), 3) if len(partner_v) else None
            ),
            "avg_visits_per_visited_school": (
                round(len(delivered) / len(visited_ids), 2) if visited_ids else 0
            ),
        }

        # ── visit quality (funnel + rates over delivered work) ─────────────
        dv = len(delivered) or 1
        with_focus = int(delivered["has_focus"].sum()) if not delivered.empty else 0
        aligned = int(delivered["aligned"].sum()) if not delivered.empty else 0
        out["quality"] = {
            "purpose_defined_rate": round(with_focus / dv, 3),
            "recommendation_alignment_rate": (
                round(aligned / with_focus, 3) if with_focus else None
            ),
            "evidence_rate": round(int(delivered["has_evidence"].sum()) / dv, 3)
            if not delivered.empty else 0,
            "salesforce_rate": round(int(delivered["has_salesforce"].sum()) / dv, 3)
            if not delivered.empty else 0,
            "ia_clearance_rate": round(int(delivered["ia_cleared"].sum()) / dv, 3)
            if not delivered.empty else 0,
            "funnel": {
                "scheduled": int(len(visits)),
                "delivered": int(len(delivered)),
                "evidence": int(delivered["has_evidence"].sum()) if not delivered.empty else 0,
                "aligned": aligned,
                "followup_ssa_available": n,  # cohort definition guarantees it
            },
        }

        # ── SSA change (overall + per intervention, association language) ──
        sch = cohort.schools.copy()
        counts = (
            delivered.groupby("school_id").size() if not delivered.empty else pd.Series(dtype=int)
        )
        sch["visit_count"] = sch["id"].map(counts.to_dict()).fillna(0).astype(int)
        improved = int((sch["overall_delta"] > 0.05).sum())
        declined = int((sch["overall_delta"] < -0.05).sum())
        out["ssa_change"] = {
            "avg_overall_delta": round(float(sch["overall_delta"].mean()), 3),
            "schools_improved": improved,
            "schools_declined": declined,
            "schools_unchanged": n - improved - declined,
            "by_school_type": {
                t: {
                    "n": int((sch["school_type"] == t).sum()),
                    "avg_delta": round(
                        float(sch.loc[sch["school_type"] == t, "overall_delta"].mean()),
                        3,
                    )
                    if (sch["school_type"] == t).any()
                    else None,
                }
                for t in ("core", "client")
            },
        }
        interventions = []
        if not cohort.scores.empty:
            g = cohort.scores.dropna(subset=["delta"]).groupby("intervention")
            agg = g.agg(
                baseline=("baseline", "mean"),
                followup=("followup", "mean"),
                delta=("delta", "mean"),
                schools=("school_id", "nunique"),
            )
            for iv in INTERVENTIONS:
                if iv in agg.index:
                    r = agg.loc[iv]
                    interventions.append(
                        {
                            "key": iv,
                            "label": INTERVENTION_LABELS[iv],
                            "baseline": round(float(r["baseline"]), 2),
                            "followup": round(float(r["followup"]), 2),
                            "delta": round(float(r["delta"]), 2),
                            "schools": int(r["schools"]),
                        }
                    )
        out["interventions"] = interventions

        # ── visits ↔ change association (never causation) ──────────────────
        assoc = {"n": n, "r": None, "p": None, "ci": None}
        valid = sch.dropna(subset=["overall_delta"])
        if len(valid) >= MIN_CORR_N and valid["visit_count"].nunique() > 1:
            res = stats.pearsonr(valid["visit_count"], valid["overall_delta"])
            ci = res.confidence_interval(0.95)
            assoc = {
                "n": int(len(valid)),
                "r": round(float(res.statistic), 4),
                "p": round(float(res.pvalue), 4),
                "ci": [round(float(ci.low), 3), round(float(ci.high), 3)],
            }
        assoc["verdict"] = _verdict(assoc["p"], assoc["n"])
        assoc["note"] = (
            "Association between delivered visit count and overall SSA change. "
            "Correlation is not causation; contextual factors are not controlled."
        )
        out["association"] = assoc

        # ── purpose mix + outcome distribution + quadrants ─────────────────
        out["purpose_mix"] = [
            {
                "key": k,
                "label": PURPOSE_LABELS[k],
                "count": int((delivered["purpose"] == k).sum()) if not delivered.empty else 0,
            }
            for k in PURPOSE_LABELS
        ]
        out["outcomes"] = {
            "improved": improved,
            "unchanged": n - improved - declined,
            "declined": declined,
            "not_yet_measurable": cohort.excluded.get("missing_followup_ssa", 0),
        }
        med_visits = float(sch["visit_count"].median())
        quads = {
            "replicate": sch[(sch["visit_count"] <= med_visits) & (sch["overall_delta"] > 0.05)],
            "review_purpose": sch[(sch["visit_count"] > med_visits) & (sch["overall_delta"] <= 0.05)],
            "efficient": sch[(sch["visit_count"] <= med_visits) & (sch["overall_delta"] > 0.5)],
            "intervene": sch[(sch["visit_count"] > med_visits) & (sch["overall_delta"] < -0.05)],
        }
        out["quadrants"] = {
            k: {
                "count": int(len(v)),
                "schools": (
                    v.sort_values("overall_delta").head(8)[
                        ["name", "visit_count", "overall_delta", "district__name"]
                    ].round(2).to_dict("records")
                    if out["scope"]["can_view_school_details"]
                    else []
                ),
            }
            for k, v in quads.items()
        }

        # ── regional variation (min-N guarded) ─────────────────────────────
        regions = []
        for reg, grp in sch.groupby("region__name", dropna=True):
            row = {
                "region": reg,
                "n": int(len(grp)),
                "avg_delta": round(float(grp["overall_delta"].mean()), 3),
                "avg_visits": round(float(grp["visit_count"].mean()), 2),
                "r": None,
                "p": None,
            }
            if len(grp) >= MIN_CORR_N and grp["visit_count"].nunique() > 1:
                res = stats.pearsonr(grp["visit_count"], grp["overall_delta"])
                row["r"] = round(float(res.statistic), 4)
                row["p"] = round(float(res.pvalue), 4)
            row["verdict"] = _verdict(row["p"], row["n"])
            row["low_sample"] = row["n"] < MIN_GROUP_N
            regions.append(row)
        out["regions"] = sorted(regions, key=lambda r: -(r["avg_delta"] or 0))

        # ── charts (JSON strings, impact_engine convention) ────────────────
        scatter = valid[["visit_count", "overall_delta", "school_type"]]
        out["charts"] = {
            "interventions": json.dumps(
                {
                    "labels": [i["label"] for i in interventions],
                    "baseline": [i["baseline"] for i in interventions],
                    "followup": [i["followup"] for i in interventions],
                    "delta": [i["delta"] for i in interventions],
                }
            ),
            "scatter": json.dumps(
                {
                    "core": scatter[scatter["school_type"] == "core"][
                        ["visit_count", "overall_delta"]
                    ].values.round(2).tolist(),
                    "client": scatter[scatter["school_type"] == "client"][
                        ["visit_count", "overall_delta"]
                    ].values.round(2).tolist(),
                }
            ),
            "purpose": json.dumps(
                {
                    "labels": [p["label"] for p in out["purpose_mix"]],
                    "counts": [p["count"] for p in out["purpose_mix"]],
                }
            ),
            "outcomes": json.dumps(out["outcomes"]),
            "funnel": json.dumps(out["quality"]["funnel"]),
        }
        out["method_notes"] = svc._method_notes()
        return out

    @staticmethod
    def _method_notes() -> list[str]:
        return [
            "Cohort: schools with a VERIFIED SSA in both the baseline and "
            "follow-up FYs; latest confirmed record per FY; FY2025 excluded "
            "(assessment-cycle change broke comparability).",
            "Visits: verified visit-type activities dated after the school's "
            "baseline assessment and on/before its follow-up. Cancelled and "
            "draft work never counts; delivered means the canonical "
            "completion chain, not a schedule entry.",
            "Alignment: a visit's focus interventions intersect the school's "
            "two weakest verified baseline interventions.",
            "All relationships are associations. Correlation is not "
            "causation, and none of these figures is a staff rating.",
            "Small groups are flagged rather than hidden "
            f"(group n<{MIN_GROUP_N}, correlation n<{MIN_CORR_N}).",
        ]

    # ── Versioned snapshot (mandate §15) ────────────────────────────────────
    @staticmethod
    def snapshot(principal, query: dict | None = None):
        from django.utils import timezone

        from .models import SchoolVisitAnalysisSnapshot

        data = SchoolVisitEffectivenessAnalyticsService.build_dashboard(
            principal, query
        )
        scope_role = getattr(principal, "active_role", "")
        current = (
            SchoolVisitAnalysisSnapshot.objects.filter(
                scope_role=scope_role,
                scope_user_id=principal.user_id,
                methodology_version=METHODOLOGY_VERSION,
            )
            .exclude(status="superseded")
            .order_by("-version")
            .first()
        )
        version = (current.version + 1) if current else 1
        if current:
            current.status = "superseded"
            current.save(update_fields=["status", "updated_at"])
        return SchoolVisitAnalysisSnapshot.objects.create(
            scope_role=scope_role,
            scope_user_id=principal.user_id,
            methodology_version=METHODOLOGY_VERSION,
            baseline_fy=data["methodology"]["baseline_fy"],
            followup_fy=data["methodology"]["followup_fy"],
            included_schools=data["cohort"]["comparable_schools"],
            excluded_summary=data["cohort"]["excluded"],
            visit_count=data.get("coverage", {}).get("delivered_visits", 0),
            data_confidence=data["cohort"]["sample_quality"],
            version=version,
            results=data,
            generated_at=timezone.now(),
        )
