"""Independent statistical integrity & edge-case regression tests for Python analytics."""

from __future__ import annotations

import math

from edify_analytics.insights import (
    CountryMetric,
    CoverageRecord,
    FieldDayFact,
    RiskInput,
    SsaRecord,
    analyze_coverage_gaps,
    analyze_route_efficiency,
    analyze_ssa,
    compute_predictive_insights,
    generate_global_report,
)
from edify_analytics.portfolio import SchoolFact, summarize


def test_analyze_ssa_preserves_real_zero_and_ignores_nan_or_out_of_range():
    records = [
        SsaRecord("s1", 0.0, 2.0, {"leadership": 0.0, "enrolment": float("nan")}),
        SsaRecord("s2", 8.0, 6.0, {"leadership": 8.0, "enrolment": 7.5}),
        SsaRecord("s3", float("nan"), 5.0, {"leadership": -1.0, "enrolment": 11.0}),
        SsaRecord("s4", None, None, {}),
    ]
    res = analyze_ssa(records)
    assert res.total_schools == 4
    assert res.assessed_schools == 2  # s1 (0.0) and s2 (8.0) only
    assert res.compared_schools == 2
    assert res.improved_schools == 1
    assert res.declined_schools == 1
    assert res.average_score == 4.0  # (0.0 + 8.0) / 2
    assert res.average_delta == 0.0  # (-2.0 + 2.0) / 2
    assert res.on_track_count == 1
    assert res.critical_count == 1
    iv_map = {iv.intervention: iv for iv in res.interventions}
    assert iv_map["leadership"].assessed_count == 2
    assert iv_map["leadership"].average_score == 4.0
    assert iv_map["enrolment"].assessed_count == 1
    assert iv_map["enrolment"].average_score == 7.5


def test_global_report_weighted_ssa_handles_zero_and_nan_safely():
    rep = generate_global_report(
        [
            CountryMetric("UG", 100, 100, 80, 6.0, 50000),
            CountryMetric("KE", 100, 100, 40, 0.0, 10000),
            CountryMetric("RW", 3, 2, 1, 7.5, 400),  # suppressed (< 5)
            CountryMetric("ET", 10, 0, 0, float("nan"), 0),
        ],
        min_cohort_size=5,
    )
    assert rep.country_count == 4
    assert math.isfinite(rep.weighted_average_ssa)
    # Weighted mean across 202 assessed schools: (6*100 + 0*100 + 7.5*2) / 202 = 615 / 202 = 3.04
    assert rep.weighted_average_ssa == round((6.0 * 100 + 0.0 * 100 + 7.5 * 2) / 202, 2)
    by_code = {c.country_code: c for c in rep.countries}
    assert by_code["RW"].suppressed is True
    assert by_code["RW"].school_count == 0
    assert by_code["ET"].average_ssa == 0.0


def test_predictive_insights_clamps_negative_days_and_explains_drivers():
    res = compute_predictive_insights(
        [
            RiskInput("s-neg", 8.2, 0.4, -15, True, True),
            RiskInput("s-high", 4.5, -1.2, 150, False, False),
        ]
    )
    assert res.low_risk_count == 1
    assert res.high_risk_count == 1
    by_id = {p.school_id: p for p in res.predictions}
    assert by_id["s-neg"].risk_score == 0.0
    assert by_id["s-high"].risk_score == 100.0
    assert len(by_id["s-high"].drivers) >= 4


def test_empty_inputs_never_divide_by_zero():
    assert summarize([]).school_count == 0
    assert analyze_ssa([]).average_score == 0.0
    assert analyze_coverage_gaps([]).overall_ssa_coverage_pct == 0.0
    assert analyze_route_efficiency([]).efficiency_score == 0.0
    assert analyze_route_efficiency([FieldDayFact("st1", 0, 0.0, 0, 0)]).average_km_per_stop == 0.0
    assert compute_predictive_insights([]).predictions == ()
    assert generate_global_report([]).weighted_average_ssa == 0.0
