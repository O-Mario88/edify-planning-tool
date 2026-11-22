"""End-to-end gRPC tests for SSA, coverage gaps, route efficiency, predictive
insights, and k-anonymized cross-country global reports."""

import grpc
import pytest
from edify.analytics.v1 import portfolio_pb2, portfolio_pb2_grpc

from edify_analytics import server as worker


@pytest.fixture(scope="module")
def stub():
    grpc_server, port = worker.build_server("127.0.0.1:0")
    grpc_server.start()
    with grpc.insecure_channel(f"127.0.0.1:{port}") as ch:
        yield portfolio_pb2_grpc.PortfolioAnalyticsServiceStub(ch)
    grpc_server.stop(0)


def test_analyze_ssa_over_grpc(stub):
    resp = stub.AnalyzeSsa(
        portfolio_pb2.AnalyzeSsaRequest(
            records=[
                portfolio_pb2.SsaSchoolRecord(
                    school_id="s1",
                    current_score=7.8,
                    previous_score=6.9,
                    intervention_scores={"Leadership": 8.0, "Financial Health": 4.5},
                ),
                portfolio_pb2.SsaSchoolRecord(
                    school_id="s2",
                    current_score=6.2,
                    previous_score=6.8,
                    intervention_scores={"Leadership": 6.0, "Financial Health": 4.9},
                ),
            ]
        ),
        timeout=5,
    )
    assert resp.total_schools == 2
    assert resp.assessed_schools == 2
    assert resp.compared_schools == 2
    assert resp.improved_schools == 1
    assert resp.declined_schools == 1
    assert resp.on_track_count == 1
    assert resp.critical_count == 1
    assert len(resp.interventions) == 2
    fin = next(i for i in resp.interventions if i.intervention == "Financial Health")
    assert fin.urgent_count == 2


def test_analyze_coverage_gaps_over_grpc(stub):
    resp = stub.AnalyzeCoverageGaps(
        portfolio_pb2.AnalyzeCoverageGapsRequest(
            records=[
                portfolio_pb2.CoverageSchoolRecord(
                    area_name="Mukono", has_ssa=True, visited=True, trained=True
                ),
                portfolio_pb2.CoverageSchoolRecord(
                    area_name="Kwania", has_ssa=False, visited=False, trained=False
                ),
                portfolio_pb2.CoverageSchoolRecord(
                    area_name="Kwania", has_ssa=False, visited=False, trained=False
                ),
            ]
        ),
        timeout=5,
    )
    assert resp.total_schools == 3
    assert resp.areas[0].area_name == "Kwania"
    assert resp.areas[0].unassessed_gap == 2
    assert resp.areas[0].composite_gap_score == 100.0


def test_analyze_route_efficiency_over_grpc(stub):
    resp = stub.AnalyzeRouteEfficiency(
        portfolio_pb2.AnalyzeRouteEfficiencyRequest(
            field_days=[
                portfolio_pb2.FieldDayRoute(
                    staff_id="u1",
                    stops_completed=4,
                    total_distance_km=40.0,
                    travel_minutes=60,
                    school_minutes=180,
                ),
                portfolio_pb2.FieldDayRoute(
                    staff_id="u2",
                    stops_completed=2,
                    total_distance_km=50.0,
                    travel_minutes=120,
                    school_minutes=120,
                ),
            ]
        ),
        timeout=5,
    )
    assert resp.field_day_count == 2
    assert resp.total_stops == 6
    assert resp.average_stops_per_day == 3.0
    assert resp.average_km_per_stop == 15.0
    assert resp.efficiency_score > 60.0


def test_compute_predictive_insights_over_grpc(stub):
    resp = stub.ComputePredictiveInsights(
        portfolio_pb2.ComputePredictiveInsightsRequest(
            schools=[
                portfolio_pb2.SchoolRiskInput(
                    school_id="at-risk",
                    latest_ssa=4.8,
                    ssa_delta=-0.9,
                    days_since_last_visit=150,
                    has_cluster=False,
                    package_complete=False,
                ),
                portfolio_pb2.SchoolRiskInput(
                    school_id="healthy",
                    latest_ssa=8.2,
                    ssa_delta=0.4,
                    days_since_last_visit=12,
                    has_cluster=True,
                    package_complete=True,
                ),
            ]
        ),
        timeout=5,
    )
    assert resp.high_risk_count == 1
    assert resp.low_risk_count == 1
    assert resp.predictions[0].school_id == "at-risk"
    assert resp.predictions[0].risk_tier == "high"


def test_generate_global_report_enforces_k_anonymity(stub):
    resp = stub.GenerateGlobalReport(
        portfolio_pb2.GenerateGlobalReportRequest(
            min_cohort_size=5,
            countries=[
                portfolio_pb2.CountryMetricInput(
                    country_code="UG",
                    school_count=700,
                    assessed_schools=500,
                    visited_schools=420,
                    average_ssa=6.9,
                    total_enrollment=120000,
                ),
                portfolio_pb2.CountryMetricInput(
                    country_code="KE",
                    school_count=3,
                    assessed_schools=2,
                    visited_schools=1,
                    average_ssa=7.2,
                    total_enrollment=600,
                ),
            ],
        ),
        timeout=5,
    )
    assert resp.country_count == 2
    assert resp.total_schools == 703
    ke = next(c for c in resp.countries if c.country_code == "KE")
    ug = next(c for c in resp.countries if c.country_code == "UG")
    assert ke.suppressed is True
    assert ke.average_ssa == 0.0
    assert ug.suppressed is False
    assert ug.average_ssa == 6.9
