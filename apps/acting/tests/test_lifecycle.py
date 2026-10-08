"""The lifecycle sweep records an appointment's life and switches nothing.

Access follows the dates (test_capacity, test_scope). These tests hold the
other half: the reminder, the start and the end each reach the audit log and
the appointee exactly once, and running the sweep, or never running it, makes
no difference to who can do what.
"""

from __future__ import annotations

import datetime

from apps.accounts.models import User
from apps.acting import lifecycle, services
from apps.acting.models import ActingAssignment
from apps.audit.models import AuditLog
from apps.core import acting as acting_api
from apps.notifications.models import Notification
from apps.realtime.registry import JOB_NAMES

from .fixtures import (
    NOVEMBER_1,
    OCTOBER_1,
    OCTOBER_15,
    SEPTEMBER_15,
    ActingFixture,
    on_day,
)

SEPTEMBER_28 = datetime.date(2026, 9, 28)


def _sweep(day):
    with on_day(day):
        return lifecycle.sweep()


class LifecycleSweepTests(ActingFixture):
    def setUp(self):
        self.appointment = self.appoint_sarah()

    def _titles(self, event):
        return list(
            Notification.objects.filter(
                recipient_id=self.sarah.id, source_event_type=event
            ).values_list("title", flat=True)
        )

    def _stored(self):
        return ActingAssignment.objects.get(id=self.appointment.id)

    def test_nothing_is_due_two_weeks_ahead(self):
        self.assertEqual(_sweep(SEPTEMBER_15), 0)
        self.assertIsNone(self._stored().reminded_at)

    def test_the_appointee_is_reminded_three_days_ahead_once(self):
        self.assertEqual(_sweep(SEPTEMBER_28), 1)
        self.assertEqual(
            self._titles("acting.reminder"),
            ["Your Acting PL assignment begins October 1."],
        )
        self.assertIsNotNone(self._stored().reminded_at)
        self.assertEqual(_sweep(SEPTEMBER_28), 0)
        self.assertEqual(len(self._titles("acting.reminder")), 1)

    def test_the_start_is_recorded_once_on_the_first_day(self):
        self.assertEqual(_sweep(OCTOBER_1), 1)
        stored = self._stored()
        self.assertIsNotNone(stored.activated_at)
        self.assertIsNone(stored.expired_at)
        row = AuditLog.objects.get(
            action="acting_assignment.activated", subject_id=self.appointment.id
        )
        self.assertEqual(row.payload["appointee"]["name"], "Sarah Officer")
        self.assertEqual(row.payload["acting_role"], "Program Lead")
        self.assertEqual(
            self._titles("acting.started"), ["You are Acting PL for October 2026."]
        )
        self.assertEqual(_sweep(OCTOBER_15), 0)

    def test_the_end_is_recorded_once_on_the_first_day_after(self):
        _sweep(OCTOBER_1)
        self.assertEqual(_sweep(NOVEMBER_1), 1)
        stored = self._stored()
        self.assertIsNotNone(stored.expired_at)
        self.assertTrue(
            AuditLog.objects.filter(
                action="acting_assignment.expired", subject_id=self.appointment.id
            ).exists()
        )
        self.assertEqual(
            self._titles("acting.ended"),
            ["Your Acting PL appointment for October 2026 has ended."],
        )
        # The hint on the account now names a day that has passed, which is
        # what spares her requests the lookup from here on.
        self.assertEqual(
            User.objects.get(id=self.sarah.id).acting_until, datetime.date(2026, 10, 31)
        )
        self.assertEqual(_sweep(NOVEMBER_1), 0)

    def test_a_cancelled_appointment_is_never_started_or_ended_by_the_sweep(self):
        with on_day(SEPTEMBER_15):
            services.cancel(self.john, self.appointment.id)
        self.assertEqual(
            _sweep(SEPTEMBER_28) + _sweep(OCTOBER_1) + _sweep(NOVEMBER_1), 0
        )
        stored = self._stored()
        self.assertIsNone(stored.activated_at)
        self.assertIsNone(stored.expired_at)

    def test_access_never_waits_for_the_sweep(self):
        """No sweep has run: she has the seat in October and not after."""
        self.assertIsNotNone(
            acting_api.acting_context(self.acting(self.sarah, OCTOBER_1))
        )
        self.assertIsNone(
            acting_api.acting_context(self.acting(self.sarah, NOVEMBER_1))
        )
        self.assertIsNone(self._stored().activated_at)

    def test_access_is_not_kept_alive_by_a_sweep_that_never_ran(self):
        """The hint on the account outlives the month; it grants nothing."""
        self.assertIsNotNone(User.objects.get(id=self.sarah.id).acting_until)
        self.assertEqual(self.acting(self.sarah, NOVEMBER_1).active_role, "CCEO")

    def test_the_job_is_registered_with_the_scheduler(self):
        from apps.realtime import jobs

        self.assertIn("acting_lifecycle", JOB_NAMES)
        self.assertTrue(callable(jobs.acting_lifecycle_job))
        with on_day(OCTOBER_1):
            self.assertEqual(jobs._do_acting_lifecycle(), 1)
