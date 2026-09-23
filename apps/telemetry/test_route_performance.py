"""Request timing and the route performance report (performance rescue).

Pins what production relies on to tell a slow page from a saturated worker:
the Server-Timing breakdown reaches signed-in users only; the slow-request log
names the route pattern and never the concrete path, user or record; the
interaction telemetry persists status, statement count, database time and
queue wait; and the System Health report turns those rows into per-route
percentiles and the checks an administrator acts on.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.core.concurrency import DatabaseConcurrencyGuardMiddleware
from apps.core.request_timing import RequestTimingMiddleware

from .models import InteractionEvent
from .performance import route_performance, route_performance_health


class RequestTimingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="timing-cceo@example.test",
            name="Timing CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
        )

    def test_signed_in_responses_carry_a_server_timing_breakdown(self):
        self.client.force_login(self.user)
        response = self.client.get("/my-targets")
        header = response["Server-Timing"]
        for part in ("app;dur=", "db;dur=", "queue;dur=", "total;dur="):
            self.assertIn(part, header)
        self.assertRegex(header, r'desc="\d+ queries"')

    def test_anonymous_responses_do_not_expose_timing(self):
        response = self.client.get("/login")
        self.assertFalse(response.has_header("Server-Timing"))

    @override_settings(SLOW_REQUEST_MS=0)
    def test_the_slow_request_log_names_the_route_pattern_only(self):
        self.client.force_login(self.user)
        with self.assertLogs("edify.perf", level="WARNING") as captured:
            self.client.get("/my-targets?school=SECRET-SCHOOL-ID")
        line = captured.output[-1]
        payload = json.loads(line.split("slow_request ", 1)[1])
        self.assertEqual(payload["route"], "my-targets")
        self.assertEqual(payload["role"], "CCEO")
        self.assertEqual(payload["status"], 200)
        self.assertGreater(payload["queries"], 0)
        for key in ("total_ms", "app_ms", "db_ms", "queue_ms", "bytes"):
            self.assertIn(key, payload)
        self.assertNotIn("SECRET-SCHOOL-ID", line)
        self.assertNotIn(str(self.user.id), line)
        self.assertNotIn(self.user.email, line)

    def test_fast_requests_are_not_logged(self):
        self.client.force_login(self.user)
        with self.assertNoLogs("edify.perf", level="WARNING"):
            self.client.get("/login")

    @override_settings(WEB_MAX_CONCURRENT_REQUESTS=2)
    def test_the_admission_guard_reports_its_wait_to_the_timer(self):
        seen = {}

        def view(request):
            from django.http import HttpResponse

            seen["queue"] = getattr(request, "edify_queue_wait_ms", None)
            return HttpResponse("ok")

        stack = RequestTimingMiddleware(DatabaseConcurrencyGuardMiddleware(view))
        request = RequestFactory().get("/dashboard")
        response = stack(request)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(seen["queue"])
        self.assertGreaterEqual(seen["queue"], 0)


@override_settings(INTERACTION_TELEMETRY_ENABLED=True)
class TelemetryPersistenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="timing-pl@example.test",
            name="Timing PL",
            roles=["Program Lead"],
            active_role="Program Lead",
            password="test-password",
            is_active=True,
        )

    def test_each_event_records_where_the_time_went(self):
        self.client.force_login(self.user)
        self.client.get("/my-targets")
        event = InteractionEvent.objects.get()
        self.assertEqual(event.status_code, 200)
        self.assertGreater(event.query_count, 0)
        self.assertGreaterEqual(event.db_ms, 0)
        self.assertEqual(event.queue_ms, 0)


class RoutePerformanceReportTests(TestCase):
    def _events(self, route, durations, *, status=200, queue_ms=0, queries=10):
        now = timezone.now()
        InteractionEvent.objects.bulk_create(
            [
                InteractionEvent(
                    user_id="u1",
                    role="CCEO",
                    occurred_at=now - timedelta(minutes=5),
                    method="GET",
                    route=route,
                    duration_ms=duration,
                    status_code=status,
                    query_count=queries,
                    db_ms=duration // 4,
                    queue_ms=queue_ms,
                )
                for duration in durations
            ]
        )

    def test_routes_rank_by_p95_with_their_breakdown(self):
        self._events("my-plan", [100] * 19 + [900])
        self._events("planning", [2000] * 10, queries=40)
        report = route_performance(window_hours=24)
        self.assertEqual(report["requests"], 30)
        self.assertEqual(
            [r["route"] for r in report["routes"]], ["planning", "my-plan"]
        )
        planning = report["routes"][0]
        self.assertEqual(planning["p50_ms"], 2000)
        self.assertEqual(planning["p95_ms"], 2000)
        self.assertEqual(planning["mean_queries"], 40)
        self.assertEqual(planning["db_p95_ms"], 500)

    def test_routes_below_the_sample_floor_are_left_out(self):
        self._events("rare-page", [5000, 5000])
        self.assertEqual(route_performance(window_hours=24)["routes"], [])

    def test_events_outside_the_window_are_ignored(self):
        InteractionEvent.objects.create(
            user_id="u1",
            role="CCEO",
            occurred_at=timezone.now() - timedelta(days=3),
            method="GET",
            route="old",
            duration_ms=9999,
        )
        self.assertEqual(route_performance(window_hours=24)["requests"], 0)

    def test_health_flags_slow_routes_saturation_and_server_errors(self):
        self._events("planning", [4000] * 10, queue_ms=2500)
        self._events("dashboard", [200] * 10, status=500)
        keys = {c["key"] for c in route_performance_health()["checks"]}
        self.assertEqual(
            keys,
            {
                "route_performance_slow_routes",
                "route_performance_queueing",
                "route_performance_server_errors",
            },
        )

    def test_a_healthy_window_raises_no_checks(self):
        self._events("dashboard", [150] * 20)
        self.assertEqual(route_performance_health()["checks"], [])
