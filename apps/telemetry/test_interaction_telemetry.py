"""The Staff Time Standard's instrument under test.

Pins the four things that make the measurement trustworthy: capture stores
route patterns and never concrete paths or query strings; sessionisation
matches the documented method exactly; the rollup is idempotent and prunes;
and the report is aggregate-only — the anti-surveillance constraint is a
test, not a promise.
"""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User

from .models import InteractionDay, InteractionEvent
from .services import (
    CATEGORY_EXECUTION,
    CATEGORY_OTHER,
    CATEGORY_PLANNING,
    FINAL_ACTION_CREDIT_SECONDS,
    IDLE_CAP_SECONDS,
    active_seconds,
    active_seconds_by_category,
    classify_route,
    interaction_report,
    rollup_interaction_days,
)


def _at(hour, minute, second=0):
    return datetime(2026, 8, 13, hour, minute, second, tzinfo=dt_timezone.utc)


class SessionisationTests(SimpleTestCase):
    def test_a_lone_event_earns_only_the_final_action_credit(self):
        self.assertEqual(active_seconds([_at(9, 0)]), FINAL_ACTION_CREDIT_SECONDS)

    def test_close_events_accumulate_their_real_gaps(self):
        # 9:00:00 → 9:01:00 → 9:02:30 = 60 + 90 gap seconds + one session
        # credit for the final interaction.
        times = [_at(9, 0), _at(9, 1), _at(9, 2, 30)]
        self.assertEqual(active_seconds(times), 150 + FINAL_ACTION_CREDIT_SECONDS)

    def test_idle_gaps_split_sessions_and_contribute_nothing(self):
        # Two sessions of 60s each; the two-hour school visit in between is
        # the person's real work, not administration.
        times = [_at(9, 0), _at(9, 1), _at(11, 30), _at(11, 31)]
        self.assertEqual(active_seconds(times), 120 + 2 * FINAL_ACTION_CREDIT_SECONDS)

    def test_the_idle_cap_is_the_boundary(self):
        start = _at(9, 0)
        exactly_cap = [start, start + timedelta(seconds=IDLE_CAP_SECONDS)]
        self.assertEqual(
            active_seconds(exactly_cap),
            IDLE_CAP_SECONDS + FINAL_ACTION_CREDIT_SECONDS,
        )
        past_cap = [start, start + timedelta(seconds=IDLE_CAP_SECONDS + 1)]
        self.assertEqual(active_seconds(past_cap), 2 * FINAL_ACTION_CREDIT_SECONDS)

    def test_unsorted_input_is_handled(self):
        times = [_at(9, 1), _at(9, 0)]
        self.assertEqual(active_seconds(times), 60 + FINAL_ACTION_CREDIT_SECONDS)


class CategoryTests(SimpleTestCase):
    def test_the_three_a_contract_classification(self):
        # Planning surfaces — the preparation the roadmap takes off staff.
        self.assertEqual(classify_route("planning/schools"), CATEGORY_PLANNING)
        self.assertEqual(classify_route("work-plan"), CATEGORY_PLANNING)
        self.assertEqual(classify_route("fund-requests/weekly"), CATEGORY_PLANNING)
        self.assertEqual(classify_route("target-distribution/team"), CATEGORY_PLANNING)
        self.assertEqual(
            classify_route("clusters/schedule-activity"), CATEGORY_PLANNING
        )
        # Execution-and-proof — the six sanctioned interactions.
        self.assertEqual(classify_route("my-plan"), CATEGORY_EXECUTION)
        self.assertEqual(
            classify_route("evidence/<str:activity_id>"), CATEGORY_EXECUTION
        )
        self.assertEqual(classify_route("debriefs/submit"), CATEGORY_EXECUTION)
        self.assertEqual(classify_route("today/action"), CATEGORY_EXECUTION)
        self.assertEqual(classify_route("todos"), CATEGORY_EXECUTION)
        # Partner Field Officers are covered field staff — their whole
        # surface counts as execution.
        self.assertEqual(classify_route("partner/my-plan"), CATEGORY_EXECUTION)
        self.assertEqual(classify_route("ssa/upload/manual"), CATEGORY_EXECUTION)
        self.assertEqual(classify_route("pl/review-queue"), CATEGORY_EXECUTION)
        # The NetSuite/SF proof endpoints must never fall to planning.
        self.assertEqual(
            classify_route("accounts/activities/<str:activity_id>/netsuite-id"),
            CATEGORY_EXECUTION,
        )
        self.assertEqual(
            classify_route("accounts/activity-evidence/<str:activity_id>"),
            CATEGORY_EXECUTION,
        )
        # Everything else is other.
        self.assertEqual(classify_route("dashboard"), CATEGORY_OTHER)
        self.assertEqual(classify_route("my-targets"), CATEGORY_OTHER)
        self.assertEqual(classify_route(""), CATEGORY_OTHER)

    def test_gaps_attribute_to_the_page_being_worked_and_totals_reconcile(self):
        # 60s on a planning page, then 30s on an execution page, then idle,
        # then a lone dashboard touch. Category totals must sum exactly to
        # the plain sessionised total for the same events.
        events = [
            (_at(9, 0), "work-plan"),
            (_at(9, 1), "my-plan"),
            (_at(9, 1, 30), "my-plan"),
            (_at(11, 0), "dashboard"),
        ]
        categories = active_seconds_by_category(events)
        self.assertEqual(categories[CATEGORY_PLANNING], 60)
        self.assertEqual(
            categories[CATEGORY_EXECUTION], 30 + FINAL_ACTION_CREDIT_SECONDS
        )
        self.assertEqual(categories[CATEGORY_OTHER], FINAL_ACTION_CREDIT_SECONDS)
        self.assertEqual(
            sum(categories.values()),
            active_seconds([time for time, _ in events]),
        )


@override_settings(INTERACTION_TELEMETRY_ENABLED=True)
class CaptureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="telemetry-cceo@example.test",
            name="Telemetry CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
        )

    def test_an_authenticated_page_view_records_a_route_pattern_only(self):
        self.client.force_login(self.user)
        self.client.get("/my-targets?fy=2027&school=SECRET-SCHOOL-ID")
        event = InteractionEvent.objects.get()
        self.assertEqual(event.user_id, str(self.user.id))
        self.assertEqual(event.role, "CCEO")
        self.assertEqual(event.method, "GET")
        # The pattern, never the concrete request: no query string, no ids.
        self.assertNotIn("SECRET-SCHOOL-ID", event.route)
        self.assertNotIn("?", event.route)

    def test_anonymous_static_and_health_traffic_is_never_recorded(self):
        self.client.get("/login")
        self.client.get("/api/health/build")
        self.client.get("/manifest.webmanifest")
        self.assertEqual(InteractionEvent.objects.count(), 0)

    @override_settings(INTERACTION_TELEMETRY_ENABLED=False)
    def test_the_flag_disables_capture_entirely(self):
        self.client.force_login(self.user)
        self.client.get("/my-targets")
        self.assertEqual(InteractionEvent.objects.count(), 0)


class RollupTests(TestCase):
    def _event(self, user_id, when, role="CCEO", method="GET", route="my-targets"):
        InteractionEvent.objects.create(
            user_id=user_id,
            role=role,
            occurred_at=when,
            method=method,
            route=route,
            duration_ms=50,
        )

    def test_rollup_writes_one_row_per_person_day_and_is_idempotent(self):
        day = timezone.localdate() - timedelta(days=1)
        base = timezone.make_aware(datetime(day.year, day.month, day.day, 9, 0))
        self._event("user-a", base, route="work-plan")
        self._event(
            "user-a",
            base + timedelta(seconds=60),
            method="POST",
            route="my-plan",
        )
        self._event("user-b", base, role="Program Lead")
        self.assertEqual(rollup_interaction_days(day=day), 2)
        self.assertEqual(rollup_interaction_days(day=day), 2)
        self.assertEqual(InteractionDay.objects.count(), 2)
        row = InteractionDay.objects.get(user_id="user-a")
        self.assertEqual(row.active_seconds, 60 + FINAL_ACTION_CREDIT_SECONDS)
        # 60s spent on the planning page; the closing execution interaction
        # earns the final-action credit — and the split reconciles exactly.
        self.assertEqual(row.planning_seconds, 60)
        self.assertEqual(row.execution_seconds, FINAL_ACTION_CREDIT_SECONDS)
        self.assertEqual(row.request_count, 2)
        self.assertEqual(row.write_count, 1)

    def test_rollup_prunes_events_past_retention(self):
        self._event("user-old", timezone.now() - timedelta(days=20))
        self._event("user-new", timezone.now() - timedelta(days=1))
        rollup_interaction_days()
        remaining = list(InteractionEvent.objects.values_list("user_id", flat=True))
        self.assertEqual(remaining, ["user-new"])


class ReportTests(TestCase):
    def _day(self, user_id, role, minutes, days_ago=1, planning_minutes=0):
        InteractionDay.objects.create(
            user_id=user_id,
            role=role,
            day=timezone.localdate() - timedelta(days=days_ago),
            active_seconds=minutes * 60,
            planning_seconds=planning_minutes * 60,
            request_count=10,
        )

    def test_percentiles_and_the_within_standard_share(self):
        for index, minutes in enumerate([5, 8, 10, 12, 40]):
            self._day(f"cceo-{index}", "CCEO", minutes)
        report = interaction_report()
        cceo = next(r for r in report["roles"] if r["role"] == "CCEO")
        self.assertEqual(cceo["person_days"], 5)
        self.assertEqual(cceo["p50_minutes"], 10.0)
        self.assertEqual(cceo["p95_minutes"], 40.0)
        self.assertEqual(cceo["within_standard_pct"], 80.0)
        self.assertTrue(cceo["covered_by_standard"])
        self.assertEqual(report["fieldPersonDays"], 5)
        self.assertEqual(report["fieldWithinStandardPct"], 80.0)
        self.assertFalse(report["meetsStandard"])

    def test_non_field_roles_are_shown_but_never_counted_in_the_slo(self):
        self._day("cceo-1", "CCEO", 10)
        self._day("ia-1", "ImpactAssessment", 200)
        report = interaction_report()
        self.assertEqual(report["fieldPersonDays"], 1)
        self.assertEqual(report["fieldWithinStandardPct"], 100.0)
        ia = next(r for r in report["roles"] if r["role"] == "ImpactAssessment")
        self.assertFalse(ia["covered_by_standard"])

    def test_the_report_is_aggregate_only_no_user_identifier_escapes(self):
        self._day("user-secret-id", "CCEO", 10)
        report = interaction_report()
        self.assertNotIn("user-secret-id", str(report))

    def test_an_empty_window_is_honest_not_zero(self):
        report = interaction_report()
        self.assertIsNone(report["fieldWithinStandardPct"])
        self.assertIsNone(report["meetsStandard"])
        self.assertIsNone(report["fieldPlanningSharePct"])

    def test_the_planning_share_measures_the_three_a_contract(self):
        # Two field days: 10 min all-planning, 10 min no-planning → 50%.
        self._day("cceo-1", "CCEO", 10, planning_minutes=10)
        self._day("cceo-2", "CCEO", 10, planning_minutes=0)
        report = interaction_report()
        self.assertEqual(report["fieldPlanningSharePct"], 50.0)
        cceo = next(r for r in report["roles"] if r["role"] == "CCEO")
        self.assertEqual(cceo["planning_share_pct"], 50.0)


class SystemHealthSurfaceTests(TestCase):
    def test_the_system_health_report_carries_the_telemetry_block(self):
        from apps.system_health.services import report

        data = report()
        self.assertIn("interactionTelemetry", data)
        self.assertIn("checks", data["interactionTelemetry"])
        # Capture is off under test, and the instrument says so honestly.
        keys = [c["key"] for c in data["interactionTelemetry"]["checks"]]
        self.assertIn("interaction_telemetry_disabled", keys)


class SchedulerRegistrationTests(SimpleTestCase):
    def test_the_rollup_job_is_registered_with_a_matching_function(self):
        from apps.realtime import jobs
        from apps.realtime.registry import JOB_REGISTRY

        spec = next(s for s in JOB_REGISTRY if s.name == "interaction_rollup")
        self.assertTrue(spec.idempotent)
        self.assertTrue(callable(jobs.interaction_rollup_job))
