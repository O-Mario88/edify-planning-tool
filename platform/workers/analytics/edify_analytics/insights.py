"""Pure analytics & intelligence engines for the Python gRPC worker.

No database drivers, no network calls, no access-control decisions. Every row
has already been scoped and authorised by the Go gateway before arrival.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class SsaRecord:
    school_id: str
    current_score: float | None
    previous_score: float | None
    interventions: Mapping[str, float]


@dataclass(frozen=True)
class InterventionStat:
    intervention: str
    assessed_count: int
    average_score: float
    min_score: float
    max_score: float
    urgent_count: int
    watch_count: int
    strong_count: int


@dataclass(frozen=True)
class SsaAnalysis:
    total_schools: int
    assessed_schools: int
    compared_schools: int
    improved_schools: int
    declined_schools: int
    average_score: float
    average_delta: float
    on_track_count: int
    watch_count: int
    critical_count: int
    interventions: tuple[InterventionStat, ...]


def analyze_ssa(records: Iterable[SsaRecord]) -> SsaAnalysis:
    rows = tuple(records)
    scores: list[float] = []
    deltas: list[float] = []
    improved = 0
    declined = 0
    on_track = 0
    watch = 0
    critical = 0
    by_iv: dict[str, list[float]] = defaultdict(list)

    for r in rows:
        if r.current_score is not None:
            scores.append(r.current_score)
            if r.current_score >= 7.5:
                on_track += 1
            elif r.current_score >= 7.0:
                watch += 1
            else:
                critical += 1
            if r.previous_score is not None:
                d = r.current_score - r.previous_score
                deltas.append(d)
                if d > 0.05:
                    improved += 1
                elif d < -0.05:
                    declined += 1
        for name, val in r.interventions.items():
            by_iv[name].append(val)

    iv_stats: list[InterventionStat] = []
    for name in sorted(by_iv.keys()):
        vals = by_iv[name]
        iv_stats.append(
            InterventionStat(
                intervention=name,
                assessed_count=len(vals),
                average_score=round(sum(vals) / len(vals), 2),
                min_score=round(min(vals), 2),
                max_score=round(max(vals), 2),
                urgent_count=sum(1 for v in vals if v < 5.0),
                watch_count=sum(1 for v in vals if 5.0 <= v < 7.0),
                strong_count=sum(1 for v in vals if v >= 7.0),
            )
        )

    return SsaAnalysis(
        total_schools=len(rows),
        assessed_schools=len(scores),
        compared_schools=len(deltas),
        improved_schools=improved,
        declined_schools=declined,
        average_score=round(sum(scores) / len(scores), 2) if scores else 0.0,
        average_delta=round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
        on_track_count=on_track,
        watch_count=watch,
        critical_count=critical,
        interventions=tuple(iv_stats),
    )


@dataclass(frozen=True)
class CoverageRecord:
    area_name: str
    has_ssa: bool
    visited: bool
    trained: bool


@dataclass(frozen=True)
class AreaGap:
    area_name: str
    total_schools: int
    ssa_covered: int
    visited_schools: int
    trained_schools: int
    ssa_coverage_pct: float
    visit_coverage_pct: float
    training_coverage_pct: float
    unassessed_gap: int
    unvisited_gap: int
    composite_gap_score: float


@dataclass(frozen=True)
class CoverageGapAnalysis:
    total_schools: int
    overall_ssa_coverage_pct: float
    overall_visit_coverage_pct: float
    overall_training_coverage_pct: float
    areas: tuple[AreaGap, ...]


def _pct(part: int, whole: int) -> float:
    return round((part / whole) * 100.0, 1) if whole > 0 else 0.0


def analyze_coverage_gaps(records: Iterable[CoverageRecord]) -> CoverageGapAnalysis:
    rows = tuple(records)
    grouped: dict[str, list[CoverageRecord]] = defaultdict(list)
    for r in rows:
        grouped[r.area_name.strip() or "Unassigned"].append(r)

    areas: list[AreaGap] = []
    for area, items in grouped.items():
        n = len(items)
        ssa = sum(1 for x in items if x.has_ssa)
        vis = sum(1 for x in items if x.visited)
        trn = sum(1 for x in items if x.trained)
        ssa_pct = _pct(ssa, n)
        vis_pct = _pct(vis, n)
        trn_pct = _pct(trn, n)
        # Higher composite_gap_score means higher urgency for intervention.
        gap_score = round(
            ((100.0 - ssa_pct) * 0.4 + (100.0 - vis_pct) * 0.4 + (100.0 - trn_pct) * 0.2), 1
        )
        areas.append(
            AreaGap(
                area_name=area,
                total_schools=n,
                ssa_covered=ssa,
                visited_schools=vis,
                trained_schools=trn,
                ssa_coverage_pct=ssa_pct,
                visit_coverage_pct=vis_pct,
                training_coverage_pct=trn_pct,
                unassessed_gap=n - ssa,
                unvisited_gap=n - vis,
                composite_gap_score=gap_score,
            )
        )
    areas.sort(key=lambda a: (-a.composite_gap_score, -a.total_schools, a.area_name))
    total = len(rows)
    return CoverageGapAnalysis(
        total_schools=total,
        overall_ssa_coverage_pct=_pct(sum(1 for r in rows if r.has_ssa), total),
        overall_visit_coverage_pct=_pct(sum(1 for r in rows if r.visited), total),
        overall_training_coverage_pct=_pct(sum(1 for r in rows if r.trained), total),
        areas=tuple(areas),
    )


@dataclass(frozen=True)
class FieldDayFact:
    staff_id: str
    stops_completed: int
    total_distance_km: float
    travel_minutes: int
    school_minutes: int


@dataclass(frozen=True)
class RouteEfficiencySummary:
    field_day_count: int
    total_stops: int
    total_distance_km: float
    average_stops_per_day: float
    average_km_per_stop: float
    school_time_share_pct: float
    efficiency_score: float


def analyze_route_efficiency(days: Iterable[FieldDayFact]) -> RouteEfficiencySummary:
    rows = tuple(days)
    if not rows:
        return RouteEfficiencySummary(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    total_stops = sum(max(0, r.stops_completed) for r in rows)
    total_km = sum(max(0.0, r.total_distance_km) for r in rows)
    total_travel = sum(max(0, r.travel_minutes) for r in rows)
    total_school = sum(max(0, r.school_minutes) for r in rows)
    avg_stops = total_stops / len(rows)
    avg_km_per_stop = (total_km / total_stops) if total_stops > 0 else 0.0
    active_mins = total_travel + total_school
    school_share = (total_school / active_mins) * 100.0 if active_mins > 0 else 0.0

    # Composite 0..100 score: rewards higher stops/day (target 4), higher
    # on-school time share (target 70%), and lower km/stop (target <= 15 km).
    stop_component = min(1.0, avg_stops / 4.0) * 40.0
    time_component = min(1.0, school_share / 70.0) * 35.0
    dist_component = (
        max(0.0, 1.0 - max(0.0, avg_km_per_stop - 10.0) / 40.0) * 25.0 if total_stops > 0 else 0.0
    )
    return RouteEfficiencySummary(
        field_day_count=len(rows),
        total_stops=total_stops,
        total_distance_km=round(total_km, 2),
        average_stops_per_day=round(avg_stops, 2),
        average_km_per_stop=round(avg_km_per_stop, 2),
        school_time_share_pct=round(school_share, 1),
        efficiency_score=round(min(100.0, stop_component + time_component + dist_component), 1),
    )


@dataclass(frozen=True)
class RiskInput:
    school_id: str
    latest_ssa: float | None
    ssa_delta: float | None
    days_since_last_visit: int
    has_cluster: bool
    package_complete: bool


@dataclass(frozen=True)
class RiskPrediction:
    school_id: str
    risk_score: float
    risk_tier: str
    drivers: tuple[str, ...]
    recommended_action: str


@dataclass(frozen=True)
class PredictiveInsights:
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    predictions: tuple[RiskPrediction, ...]


def compute_predictive_insights(schools: Iterable[RiskInput]) -> PredictiveInsights:
    preds: list[RiskPrediction] = []
    high = medium = low = 0

    for s in schools:
        score = 0.0
        drivers: list[str] = []
        if s.latest_ssa is None:
            score += 25.0
            drivers.append("No confirmed SSA assessment")
        elif s.latest_ssa < 5.5:
            score += 40.0
            drivers.append(f"Critical SSA score ({s.latest_ssa:.1f}/10)")
        elif s.latest_ssa < 7.0:
            score += 22.0
            drivers.append(f"Below-target SSA score ({s.latest_ssa:.1f}/10)")

        if s.ssa_delta is not None and s.ssa_delta <= -0.5:
            score += 25.0
            drivers.append(f"SSA declined ({s.ssa_delta:+.1f} pts)")

        if s.days_since_last_visit >= 120:
            score += 20.0
            drivers.append(f"No visit in {s.days_since_last_visit} days")
        elif s.days_since_last_visit >= 60:
            score += 10.0
            drivers.append(f"Visit aging ({s.days_since_last_visit} days)")

        if not s.has_cluster:
            score += 10.0
            drivers.append("Unclustered school")
        if not s.package_complete:
            score += 10.0
            drivers.append("Support package incomplete")

        score = min(100.0, round(score, 1))
        if score >= 60.0:
            tier = "high"
            high += 1
            rec = "Schedule urgent diagnostic visit and targeted SSA intervention"
        elif score >= 30.0:
            tier = "medium"
            medium += 1
            rec = "Prioritise follow-up visit and close open package items"
        else:
            tier = "low"
            low += 1
            rec = "Maintain routine cluster engagement"

        preds.append(
            RiskPrediction(
                school_id=s.school_id,
                risk_score=score,
                risk_tier=tier,
                drivers=tuple(drivers),
                recommended_action=rec,
            )
        )

    preds.sort(key=lambda p: (-p.risk_score, p.school_id))
    return PredictiveInsights(
        high_risk_count=high,
        medium_risk_count=medium,
        low_risk_count=low,
        predictions=tuple(preds),
    )


@dataclass(frozen=True)
class CountryMetric:
    country_code: str
    school_count: int
    assessed_schools: int
    visited_schools: int
    average_ssa: float
    total_enrollment: int


@dataclass(frozen=True)
class CountryRollup:
    country_code: str
    school_count: int
    ssa_coverage_pct: float
    visit_coverage_pct: float
    average_ssa: float
    total_enrollment: int
    suppressed: bool


@dataclass(frozen=True)
class GlobalReport:
    country_count: int
    total_schools: int
    total_enrollment: int
    weighted_average_ssa: float
    overall_ssa_coverage_pct: float
    overall_visit_coverage_pct: float
    countries: tuple[CountryRollup, ...]


def generate_global_report(
    countries: Iterable[CountryMetric], min_cohort_size: int = 5
) -> GlobalReport:
    """Produce an anonymized cross-country rollup. Countries with fewer schools
    than min_cohort_size have school-level averages suppressed (k-anonymity)."""
    threshold = max(1, min_cohort_size)
    rows = tuple(countries)
    out: list[CountryRollup] = []
    tot_schools = 0
    tot_assessed = 0
    tot_visited = 0
    tot_enrollment = 0
    weighted_ssa_num = 0.0

    for c in sorted(rows, key=lambda x: x.country_code):
        code = c.country_code.strip().upper()
        n = max(0, c.school_count)
        assessed = max(0, min(n, c.assessed_schools))
        visited = max(0, min(n, c.visited_schools))
        suppressed = n < threshold

        tot_schools += n
        tot_assessed += assessed
        tot_visited += visited
        tot_enrollment += max(0, c.total_enrollment)
        if assessed > 0 and c.average_ssa > 0:
            weighted_ssa_num += c.average_ssa * assessed

        out.append(
            CountryRollup(
                country_code=code,
                school_count=0 if suppressed else n,
                ssa_coverage_pct=0.0 if suppressed else _pct(assessed, n),
                visit_coverage_pct=0.0 if suppressed else _pct(visited, n),
                average_ssa=0.0 if suppressed else round(c.average_ssa, 2),
                total_enrollment=0 if suppressed else max(0, c.total_enrollment),
                suppressed=suppressed,
            )
        )

    return GlobalReport(
        country_count=len(out),
        total_schools=tot_schools,
        total_enrollment=tot_enrollment,
        weighted_average_ssa=round(weighted_ssa_num / tot_assessed, 2) if tot_assessed > 0 else 0.0,
        overall_ssa_coverage_pct=_pct(tot_assessed, tot_schools),
        overall_visit_coverage_pct=_pct(tot_visited, tot_schools),
        countries=tuple(out),
    )
