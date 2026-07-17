"""SSA improvement analytics + decision-recommendations engine.

Computes from real SSA records only:
  • Per-school SSA improvement delta (current FY vs previous FY, same school).
  • Intervention-level averages + deltas across all 8 interventions.
  • School improvement classification (improved / declined / no-change).
  • District/cluster SSA performance rollups.
  • Role-specific decision recommendations generated from real risk conditions.

No mock data. Every number traces to SsaRecord/SsaScore rows. Improvement
requires ≥2 SSA records for the SAME school — never compares different schools.
"""

from __future__ import annotations

from django.db.models import Avg, Count

from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope
from apps.schools.models import School

from .platform_engine import describe_numeric, engine_metadata


# Configurable improvement thresholds (a school "improved" if delta > +0.3,
# "declined" if delta < -0.3; within ±0.3 = "no_change").
IMPROVEMENT_THRESHOLD = 0.3
DECLINE_THRESHOLD = -0.3

ALL_INTERVENTIONS = [i.value for i in SsaIntervention]


def _scoped_school_ids(principal) -> list[str]:
    """Resolve the in-scope school PKs for a principal."""
    scope = resolve_user_scope(principal)
    if scope.country_scope or scope.can_view_summary_only:
        return list(
            School.objects.filter(deleted_at__isnull=True).values_list("id", flat=True)
        )
    if scope.school_ids:
        return scope.school_ids
    return []


# ── SSA improvement (per-school delta) ───────────────────────────────────────


def ssa_improvement(principal, query: dict) -> dict:
    """Per-school SSA improvement: current FY average vs previous FY average.

    For each school with ≥2 SSA records (one current, one previous), compute:
      delta = current_avg - previous_avg
      status = improved (delta > +0.3) | declined (delta < -0.3) | no_change

    Returns overall stats + the improved/declined school lists (with drilldown
    school IDs so the frontend can show exactly those schools)."""
    from apps.ssa.models import SsaRecord

    fy = query.get("fy") or get_operational_fy()
    prev_fy = str(int(fy) - 1)
    school_ids = _scoped_school_ids(principal)
    if not school_ids:
        return _empty_improvement(fy)

    # Current + previous FY averages per school (one query each, grouped).
    curr = dict(
        SsaRecord.objects.filter(
            school_id__in=school_ids,
            fy=fy,
            deleted_at__isnull=True,
            verification_status="confirmed",
        )
        .values("school_id")
        .annotate(avg=Avg("average_score"))
        .values_list("school_id", "avg")
    )
    prev = dict(
        SsaRecord.objects.filter(
            school_id__in=school_ids,
            fy=prev_fy,
            deleted_at__isnull=True,
            verification_status="confirmed",
        )
        .values("school_id")
        .annotate(avg=Avg("average_score"))
        .values_list("school_id", "avg")
    )

    improved, declined, no_change = [], [], []
    deltas = []
    for sid in school_ids:
        if sid not in curr or sid not in prev:
            continue
        delta = round(curr[sid] - prev[sid], 2)
        deltas.append(delta)
        school = (
            School.objects.filter(id=sid)
            .values("school_id", "name", "district__name")
            .first()
        )
        entry = {
            "schoolId": school["school_id"] if school else sid,
            "schoolName": school["name"] if school else "Unknown",
            "district": school["district__name"] if school else None,
            "currentScore": round(curr[sid], 2),
            "previousScore": round(prev[sid], 2),
            "delta": delta,
        }
        if delta > IMPROVEMENT_THRESHOLD:
            improved.append(entry)
        elif delta < DECLINE_THRESHOLD:
            declined.append(entry)
        else:
            no_change.append(entry)

    delta_summary = describe_numeric(deltas, target=IMPROVEMENT_THRESHOLD)
    avg_delta = delta_summary["mean"] or 0
    return {
        "fy": fy,
        "previousFy": prev_fy,
        "schoolsCompared": len(deltas),
        "averageDelta": avg_delta,
        "improvedCount": len(improved),
        "declinedCount": len(declined),
        "noChangeCount": len(no_change),
        "improved": sorted(improved, key=lambda x: -x["delta"])[:50],
        "declined": sorted(declined, key=lambda x: x["delta"])[:50],
        "improvedSchoolIds": [e["schoolId"] for e in improved],
        "declinedSchoolIds": [e["schoolId"] for e in declined],
        "analytics": {
            "delta": delta_summary,
            "engine": engine_metadata(
                "ssa_improvement", record_count=len(deltas), confirmed_only=True
            ),
        },
    }


def _empty_improvement(fy: str) -> dict:
    return {
        "fy": fy,
        "previousFy": str(int(fy) - 1),
        "schoolsCompared": 0,
        "averageDelta": 0,
        "improvedCount": 0,
        "declinedCount": 0,
        "noChangeCount": 0,
        "improved": [],
        "declined": [],
        "improvedSchoolIds": [],
        "declinedSchoolIds": [],
        "analytics": {
            "delta": describe_numeric([], target=IMPROVEMENT_THRESHOLD),
            "engine": engine_metadata(
                "ssa_improvement", record_count=0, confirmed_only=True
            ),
        },
    }


# ── Intervention-level analytics ────────────────────────────────────────────


def intervention_analytics(principal, query: dict) -> dict:
    """Per-intervention averages (current + previous FY) + delta + below-threshold
    school counts. The 8 interventions with their trend."""
    from apps.ssa.models import SsaScore

    fy = query.get("fy") or get_operational_fy()
    prev_fy = str(int(fy) - 1)
    school_ids = _scoped_school_ids(principal)

    out = {}
    for interv in ALL_INTERVENTIONS:
        curr = SsaScore.objects.filter(
            ssa_record__school_id__in=school_ids,
            ssa_record__fy=fy,
            ssa_record__deleted_at__isnull=True,
            ssa_record__verification_status="confirmed",
            intervention=interv,
        ).aggregate(a=Avg("score"))["a"]
        prev = SsaScore.objects.filter(
            ssa_record__school_id__in=school_ids,
            ssa_record__fy=prev_fy,
            ssa_record__deleted_at__isnull=True,
            ssa_record__verification_status="confirmed",
            intervention=interv,
        ).aggregate(a=Avg("score"))["a"]
        delta = (
            round(curr - prev, 2) if (curr is not None and prev is not None) else None
        )
        below_threshold = SsaScore.objects.filter(
            ssa_record__school_id__in=school_ids,
            ssa_record__fy=fy,
            ssa_record__deleted_at__isnull=True,
            ssa_record__verification_status="confirmed",
            intervention=interv,
            score__lt=5.0,
        ).count()
        out[interv] = {
            "current": round(curr, 2) if curr else None,
            "previous": round(prev, 2) if prev else None,
            "delta": delta,
            "schoolsBelowThreshold": below_threshold,
        }
    # Rank by current score (strongest → weakest).
    ranked = sorted(out.items(), key=lambda x: -(x[1]["current"] or 0))
    return {
        "fy": fy,
        "interventions": out,
        "weakest": ranked[-1][0] if ranked else None,
        "strongest": ranked[0][0] if ranked else None,
        "ranking": [r[0] for r in ranked],
    }


# ── District / cluster SSA rollups ──────────────────────────────────────────


def district_ssa_rollup(principal, query: dict) -> list[dict]:
    """SSA performance per district: avg score, school count, improved/declined."""
    from apps.ssa.models import SsaRecord

    fy = query.get("fy") or get_operational_fy()
    school_ids = _scoped_school_ids(principal)
    records = (
        SsaRecord.objects.filter(
            school_id__in=school_ids,
            fy=fy,
            deleted_at__isnull=True,
        )
        .values("school__district__name")
        .annotate(
            avg=Avg("average_score"),
            count=Count("id"),
        )
        .order_by("school__district__name")
    )
    return [
        {
            "district": r["school__district__name"],
            "averageScore": round(r["avg"], 2) if r["avg"] else None,
            "ssaCount": r["count"],
        }
        for r in records
        if r["school__district__name"]
    ]


def cluster_ssa_rollup(principal, query: dict) -> list[dict]:
    """SSA performance per cluster. School.cluster_id is a plain CharField ref
    (not a Django FK named 'cluster'), so we resolve cluster names separately."""
    from apps.ssa.models import SsaRecord
    from apps.clusters.models import Cluster

    fy = query.get("fy") or get_operational_fy()
    school_ids = _scoped_school_ids(principal)
    records = (
        SsaRecord.objects.filter(
            school_id__in=school_ids,
            fy=fy,
            deleted_at__isnull=True,
            school__cluster_id__isnull=False,
        )
        .values("school__cluster_id")
        .annotate(
            avg=Avg("average_score"),
            count=Count("id"),
        )
        .order_by("-avg")
    )
    # Resolve cluster names.
    cluster_ids = [r["school__cluster_id"] for r in records]
    cluster_names = dict(
        Cluster.objects.filter(id__in=cluster_ids).values_list("id", "name")
    )
    return [
        {
            "clusterId": r["school__cluster_id"],
            "clusterName": cluster_names.get(r["school__cluster_id"], "Unknown"),
            "averageScore": round(r["avg"], 2) if r["avg"] else None,
            "ssaCount": r["count"],
        }
        for r in records
    ]


# ── Decision recommendations ────────────────────────────────────────────────


def recommendations(principal, query: dict) -> list[dict]:
    """Role-specific decision recommendations generated from real risk conditions.

    Each recommendation has: priority, reason, affectedRecords, suggestedAction,
    link, roleOwner. Generated from live data — no hardcoded recommendations."""
    school_ids = _scoped_school_ids(principal)
    role = principal.active_role
    recs: list[dict] = []

    if not school_ids:
        return recs

    # 1. Schools without SSA (planning locked) — highest priority.
    from apps.schools.models import School as _S

    no_ssa = _S.objects.filter(
        id__in=school_ids, current_fy_ssa_status__in=["not_done", "scheduled"]
    ).count()
    if no_ssa > 0:
        recs.append(
            {
                "priority": "high",
                "reason": f"{no_ssa} schools have no current-FY SSA — planning is locked for them.",
                "affectedCount": no_ssa,
                "suggestedAction": "Upload SSA for these schools to unlock planning.",
                "link": "/ssa",
                "roleOwner": "ImpactAssessment",
            }
        )

    # 2. Schools with declining SSA (need intervention).
    improvement = ssa_improvement(principal, query)
    if improvement["declinedCount"] > 0:
        weakest_interventions = intervention_analytics(principal, query)
        weakest = weakest_interventions.get("weakest", "unknown")
        recs.append(
            {
                "priority": "high",
                "reason": f"{improvement['declinedCount']} schools have declining SSA (avg delta {improvement['averageDelta']:.1f}). Weakest intervention: {weakest}.",
                "affectedCount": improvement["declinedCount"],
                "suggestedAction": f"Schedule visits or group training focused on {weakest.replace('_', ' ')} for these schools.",
                "link": "/schools",
                "roleOwner": role,
            }
        )

    # 3. Clusters with low SSA averages (need training).
    cluster_rollup = cluster_ssa_rollup(principal, query)
    weak_clusters = [
        c for c in cluster_rollup if c["averageScore"] and c["averageScore"] < 5.0
    ]
    if weak_clusters:
        recs.append(
            {
                "priority": "medium",
                "reason": f"{len(weak_clusters)} cluster(s) have an average SSA below 5.0.",
                "affectedCount": len(weak_clusters),
                "suggestedAction": "Schedule group training for these clusters.",
                "link": "/clusters",
                "roleOwner": role,
            }
        )

    # 4. Weakest intervention nationally/regionally.
    interventions = intervention_analytics(principal, query)
    weakest = interventions.get("weakest")
    if weakest:
        weak_data = interventions["interventions"].get(weakest, {})
        below = weak_data.get("schoolsBelowThreshold", 0)
        if below > 0:
            recs.append(
                {
                    "priority": "medium",
                    "reason": f"'{weakest.replace('_', ' ').title()}' is the weakest intervention (avg {weak_data.get('current', '?')}) with {below} schools below 5.0.",
                    "affectedCount": below,
                    "suggestedAction": f"Focus training and coaching on {weakest.replace('_', ' ')}.",
                    "link": "/analytics",
                    "roleOwner": role,
                }
            )

    # Sort by priority.
    priority_order = {"high": 0, "medium": 1, "low": 2}
    recs.sort(key=lambda r: priority_order.get(r["priority"], 9))
    return recs


def ssa_performance_dashboard(principal, query: dict) -> dict:
    """Decision-engine view model for the unified SSA Performance workspace.

    Kept on the engine's public surface so the web page, exports, and any later
    API adapter cannot drift into separate risk or recommendation rules.
    """
    from .ssa_performance_service import build_dashboard

    return build_dashboard(principal, query)


def impact_analytics_dashboard(principal, query: dict) -> dict:
    """Decision-engine view model for the statistical Impact Analytics
    workspace (visits/trainings/funding/targets/geography/debriefs vs SSA
    improvement). Same facade rule as ssa_performance_dashboard."""
    from .impact_engine import build_dashboard

    return build_dashboard(principal, query)


__all__ = [
    "ssa_improvement",
    "intervention_analytics",
    "district_ssa_rollup",
    "cluster_ssa_rollup",
    "recommendations",
    "ssa_performance_dashboard",
    "impact_analytics_dashboard",
]
