"""gRPC server of the analytics worker (internal: the Go gateway is its only
caller).

    PYTHONPATH=gen python -m edify_analytics.server

The worker refuses to start when its environment carries database connection
settings. It has no database driver installed and needs none; a database URL
in its environment means it was deployed with configuration it must not have.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from collections.abc import Mapping
from concurrent import futures

import grpc
from edify.analytics.v1 import portfolio_pb2, portfolio_pb2_grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

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

DEFAULT_ADDRESS = "127.0.0.1:50061"
ADDRESS_ENV = "EDIFY_ANALYTICS_ADDR"
MAX_SCHOOLS = 20_000
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
MAX_WORKERS = 4
SHUTDOWN_GRACE_SECONDS = 10
SERVICE_NAME = "edify.analytics.v1.PortfolioAnalyticsService"

# Connection settings this worker must never be given.
FORBIDDEN_ENV = (
    "DATABASE_URL",
    "EDIFY_DATABASE_URL",
    "EDIFY_ADMIN_DATABASE_URL",
    "PGHOST",
    "PGPASSWORD",
    "PGDATABASE",
    "PGSERVICE",
)

logger = logging.getLogger("edify.analytics")


class DatabaseConfigurationPresentError(RuntimeError):
    """The worker was started with database connection settings."""


def assert_no_database_configuration(environ: Mapping[str, str]) -> None:
    present = sorted(name for name in FORBIDDEN_ENV if environ.get(name))
    if present:
        raise DatabaseConfigurationPresentError(
            "the analytics worker holds no database connection; remove "
            + ", ".join(present)
            + " from its environment"
        )


class PortfolioAnalyticsService(portfolio_pb2_grpc.PortfolioAnalyticsServiceServicer):
    def SummarizePortfolio(  # noqa: N802 - gRPC method name
        self,
        request: portfolio_pb2.SummarizePortfolioRequest,
        context: grpc.ServicerContext,
    ) -> portfolio_pb2.SummarizePortfolioResponse:
        metadata = dict(context.invocation_metadata())
        if len(request.schools) > MAX_SCHOOLS:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"at most {MAX_SCHOOLS} schools per request",
            )
        summary = summarize(
            SchoolFact(
                school_type=school.school_type,
                enrollment=school.enrollment if school.HasField("enrollment") else None,
            )
            for school in request.schools
        )
        logger.info(
            "summarized portfolio schools=%d request_id=%s traceparent=%s",
            summary.school_count,
            metadata.get("x-request-id", ""),
            metadata.get("traceparent", ""),
        )
        return portfolio_pb2.SummarizePortfolioResponse(
            school_count=summary.school_count,
            schools_by_type=dict(summary.schools_by_type),
            schools_with_enrollment=summary.schools_with_enrollment,
            total_enrollment=summary.total_enrollment,
            median_enrollment=summary.median_enrollment,
        )

    def AnalyzeSsa(  # noqa: N802
        self,
        request: portfolio_pb2.AnalyzeSsaRequest,
        context: grpc.ServicerContext,
    ) -> portfolio_pb2.AnalyzeSsaResponse:
        if len(request.records) > MAX_SCHOOLS:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, f"at most {MAX_SCHOOLS} records per request"
            )
        res = analyze_ssa(
            SsaRecord(
                school_id=r.school_id,
                current_score=r.current_score if r.HasField("current_score") else None,
                previous_score=r.previous_score if r.HasField("previous_score") else None,
                interventions=dict(r.intervention_scores),
            )
            for r in request.records
        )
        return portfolio_pb2.AnalyzeSsaResponse(
            total_schools=res.total_schools,
            assessed_schools=res.assessed_schools,
            compared_schools=res.compared_schools,
            improved_schools=res.improved_schools,
            declined_schools=res.declined_schools,
            average_score=res.average_score,
            average_delta=res.average_delta,
            on_track_count=res.on_track_count,
            watch_count=res.watch_count,
            critical_count=res.critical_count,
            interventions=[
                portfolio_pb2.InterventionSummary(
                    intervention=iv.intervention,
                    assessed_count=iv.assessed_count,
                    average_score=iv.average_score,
                    min_score=iv.min_score,
                    max_score=iv.max_score,
                    urgent_count=iv.urgent_count,
                    watch_count=iv.watch_count,
                    strong_count=iv.strong_count,
                )
                for iv in res.interventions
            ],
        )

    def AnalyzeCoverageGaps(  # noqa: N802
        self,
        request: portfolio_pb2.AnalyzeCoverageGapsRequest,
        context: grpc.ServicerContext,
    ) -> portfolio_pb2.AnalyzeCoverageGapsResponse:
        if len(request.records) > MAX_SCHOOLS:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, f"at most {MAX_SCHOOLS} records per request"
            )
        res = analyze_coverage_gaps(
            CoverageRecord(
                area_name=r.area_name,
                has_ssa=r.has_ssa,
                visited=r.visited,
                trained=r.trained,
            )
            for r in request.records
        )
        return portfolio_pb2.AnalyzeCoverageGapsResponse(
            total_schools=res.total_schools,
            overall_ssa_coverage_pct=res.overall_ssa_coverage_pct,
            overall_visit_coverage_pct=res.overall_visit_coverage_pct,
            overall_training_coverage_pct=res.overall_training_coverage_pct,
            areas=[
                portfolio_pb2.AreaCoverageGap(
                    area_name=a.area_name,
                    total_schools=a.total_schools,
                    ssa_covered=a.ssa_covered,
                    visited_schools=a.visited_schools,
                    trained_schools=a.trained_schools,
                    ssa_coverage_pct=a.ssa_coverage_pct,
                    visit_coverage_pct=a.visit_coverage_pct,
                    training_coverage_pct=a.training_coverage_pct,
                    unassessed_gap=a.unassessed_gap,
                    unvisited_gap=a.unvisited_gap,
                    composite_gap_score=a.composite_gap_score,
                )
                for a in res.areas
            ],
        )

    def AnalyzeRouteEfficiency(  # noqa: N802
        self,
        request: portfolio_pb2.AnalyzeRouteEfficiencyRequest,
        context: grpc.ServicerContext,
    ) -> portfolio_pb2.AnalyzeRouteEfficiencyResponse:
        if len(request.field_days) > MAX_SCHOOLS:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, f"at most {MAX_SCHOOLS} field days per request"
            )
        res = analyze_route_efficiency(
            FieldDayFact(
                staff_id=d.staff_id,
                stops_completed=d.stops_completed,
                total_distance_km=d.total_distance_km,
                travel_minutes=d.travel_minutes,
                school_minutes=d.school_minutes,
            )
            for d in request.field_days
        )
        return portfolio_pb2.AnalyzeRouteEfficiencyResponse(
            field_day_count=res.field_day_count,
            total_stops=res.total_stops,
            total_distance_km=res.total_distance_km,
            average_stops_per_day=res.average_stops_per_day,
            average_km_per_stop=res.average_km_per_stop,
            school_time_share_pct=res.school_time_share_pct,
            efficiency_score=res.efficiency_score,
        )

    def ComputePredictiveInsights(  # noqa: N802
        self,
        request: portfolio_pb2.ComputePredictiveInsightsRequest,
        context: grpc.ServicerContext,
    ) -> portfolio_pb2.ComputePredictiveInsightsResponse:
        if len(request.schools) > MAX_SCHOOLS:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, f"at most {MAX_SCHOOLS} schools per request"
            )
        res = compute_predictive_insights(
            RiskInput(
                school_id=s.school_id,
                latest_ssa=s.latest_ssa if s.HasField("latest_ssa") else None,
                ssa_delta=s.ssa_delta if s.HasField("ssa_delta") else None,
                days_since_last_visit=s.days_since_last_visit,
                has_cluster=s.has_cluster,
                package_complete=s.package_complete,
            )
            for s in request.schools
        )
        return portfolio_pb2.ComputePredictiveInsightsResponse(
            high_risk_count=res.high_risk_count,
            medium_risk_count=res.medium_risk_count,
            low_risk_count=res.low_risk_count,
            predictions=[
                portfolio_pb2.SchoolRiskPrediction(
                    school_id=p.school_id,
                    risk_score=p.risk_score,
                    risk_tier=p.risk_tier,
                    drivers=list(p.drivers),
                    recommended_action=p.recommended_action,
                )
                for p in res.predictions
            ],
        )

    def GenerateGlobalReport(  # noqa: N802
        self,
        request: portfolio_pb2.GenerateGlobalReportRequest,
        context: grpc.ServicerContext,
    ) -> portfolio_pb2.GenerateGlobalReportResponse:
        res = generate_global_report(
            (
                CountryMetric(
                    country_code=c.country_code,
                    school_count=c.school_count,
                    assessed_schools=c.assessed_schools,
                    visited_schools=c.visited_schools,
                    average_ssa=c.average_ssa,
                    total_enrollment=c.total_enrollment,
                )
                for c in request.countries
            ),
            min_cohort_size=request.min_cohort_size or 5,
        )
        return portfolio_pb2.GenerateGlobalReportResponse(
            country_count=res.country_count,
            total_schools=res.total_schools,
            total_enrollment=res.total_enrollment,
            weighted_average_ssa=res.weighted_average_ssa,
            overall_ssa_coverage_pct=res.overall_ssa_coverage_pct,
            overall_visit_coverage_pct=res.overall_visit_coverage_pct,
            countries=[
                portfolio_pb2.CountryGlobalRow(
                    country_code=row.country_code,
                    school_count=row.school_count,
                    ssa_coverage_pct=row.ssa_coverage_pct,
                    visit_coverage_pct=row.visit_coverage_pct,
                    average_ssa=row.average_ssa,
                    total_enrollment=row.total_enrollment,
                    suppressed=row.suppressed,
                )
                for row in res.countries
            ],
        )


def build_server(address: str) -> tuple[grpc.Server, int]:
    """Create the server bound to address; returns it with the bound port."""
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=MAX_WORKERS),
        options=[
            ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
            ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
        ],
    )
    portfolio_pb2_grpc.add_PortfolioAnalyticsServiceServicer_to_server(
        PortfolioAnalyticsService(), server
    )
    health_servicer = health.HealthServicer()
    health_servicer.set(SERVICE_NAME, health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    # Plaintext on a private address: the gateway is the only caller. Mutual
    # TLS is a staging exit criterion (docs/migration/05-environments-and-staging.md).
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"could not bind {address}")
    return server, port


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        assert_no_database_configuration(os.environ)
    except DatabaseConfigurationPresentError as error:
        logger.error("refusing to start: %s", error)
        return 1

    address = os.environ.get(ADDRESS_ENV, DEFAULT_ADDRESS)
    server, port = build_server(address)
    server.start()
    logger.info("analytics worker listening address=%s port=%d", address, port)

    def stop(*_: object) -> None:
        server.stop(SHUTDOWN_GRACE_SECONDS)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.wait_for_termination()
    return 0


if __name__ == "__main__":
    sys.exit(main())
