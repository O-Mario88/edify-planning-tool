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
