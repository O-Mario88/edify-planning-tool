"""The worker over a real gRPC connection, and its no-database guarantees."""

import re
from pathlib import Path

import grpc
import pytest
from edify.analytics.v1 import portfolio_pb2, portfolio_pb2_grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

from edify_analytics import server as worker

WORKER_ROOT = Path(__file__).resolve().parents[1]
DATABASE_DRIVERS = re.compile(
    r"psycopg|asyncpg|sqlalchemy|pymysql|pg8000|django|peewee|sqlite3|pymongo|redis", re.I
)


@pytest.fixture(scope="module")
def channel():
    grpc_server, port = worker.build_server("127.0.0.1:0")
    grpc_server.start()
    with grpc.insecure_channel(f"127.0.0.1:{port}") as open_channel:
        yield open_channel
    grpc_server.stop(0)


def school(school_type, enrollment=None):
    if enrollment is None:
        return portfolio_pb2.PortfolioSchool(school_type=school_type)
    return portfolio_pb2.PortfolioSchool(school_type=school_type, enrollment=enrollment)


def test_summarize_portfolio_over_grpc(channel):
    stub = portfolio_pb2_grpc.PortfolioAnalyticsServiceStub(channel)

    response = stub.SummarizePortfolio(
        portfolio_pb2.SummarizePortfolioRequest(
            schools=[school("client", 100), school("client"), school("core", 300)]
        ),
        metadata=(("x-request-id", "test-req-0001"),),
        timeout=5,
    )

    assert response.school_count == 3
    assert dict(response.schools_by_type) == {"client": 2, "core": 1}
    assert response.schools_with_enrollment == 2
    assert response.total_enrollment == 400
    assert response.median_enrollment == 200.0


def test_an_explicit_zero_enrollment_survives_the_wire(channel):
    stub = portfolio_pb2_grpc.PortfolioAnalyticsServiceStub(channel)

    response = stub.SummarizePortfolio(
        portfolio_pb2.SummarizePortfolioRequest(schools=[school("client", 0)]), timeout=5
    )

    assert response.schools_with_enrollment == 1


def test_oversized_requests_are_refused(channel, monkeypatch):
    monkeypatch.setattr(worker, "MAX_SCHOOLS", 2)
    stub = portfolio_pb2_grpc.PortfolioAnalyticsServiceStub(channel)

    with pytest.raises(grpc.RpcError) as failure:
        stub.SummarizePortfolio(
            portfolio_pb2.SummarizePortfolioRequest(schools=[school("client")] * 3), timeout=5
        )

    assert failure.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_health_service_reports_serving(channel):
    stub = health_pb2_grpc.HealthStub(channel)

    response = stub.Check(health_pb2.HealthCheckRequest(service=worker.SERVICE_NAME), timeout=5)

    assert response.status == health_pb2.HealthCheckResponse.SERVING


@pytest.mark.parametrize("name", worker.FORBIDDEN_ENV)
def test_the_worker_refuses_to_start_with_database_settings(name):
    with pytest.raises(worker.DatabaseConfigurationPresentError, match=name):
        worker.assert_no_database_configuration({name: "postgresql://somewhere/db"})


def test_the_worker_starts_without_database_settings():
    environment = {"EDIFY_ANALYTICS_ADDR": "127.0.0.1:50061", "PGHOST": ""}

    worker.assert_no_database_configuration(environment)


def test_no_database_driver_is_a_dependency_or_an_import():
    requirements = (WORKER_ROOT / "requirements.txt").read_text()
    declared = [line for line in requirements.splitlines() if not line.lstrip().startswith("#")]
    assert not DATABASE_DRIVERS.search("\n".join(declared)), "a database driver was added"

    for source in (WORKER_ROOT / "edify_analytics").glob("*.py"):
        imports = [
            line
            for line in source.read_text().splitlines()
            if line.lstrip().startswith(("import ", "from "))
        ]
        assert not DATABASE_DRIVERS.search("\n".join(imports)), f"{source.name} imports a driver"
