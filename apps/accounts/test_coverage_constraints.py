"""One active coverage per leave request, and a window that runs forwards
(INT-02).

TemporaryCoverageAssignment's Meta contained only db_table. "One active
assignment" was held up by a revoke-then-create pair under a row lock in one
code path, so any other writer could hand a second person the same absent
employee's authority — and _covered_staff_ids and review_authority
._covering_for both return EVERY match rather than picking one.

The most important test in this file is
`test_a_later_leave_gets_its_own_coverage_despite_the_stale_status`. `is_live`
warns that nothing in the codebase ever writes status="expired", so every
grant ever created still reads "active". A partial index keyed on anything
that RECURS for a person would therefore refuse a legitimate new delegation
because of one from years ago. That test is the proof this key does not.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import count

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Leave, StaffProfile, TemporaryCoverageAssignment
from apps.core.rbac import EdifyRole

User = get_user_model()

_ids = count(1)


class CoverageFixture(TestCase):
    """Fixture + helpers shared by the constraint tests and the guard
    tests below."""

    @classmethod
    def setUpTestData(cls):
        cls.absent = cls._staff("absent@cov.test", "Amina Absent", EdifyRole.CCEO)
        cls.cover = cls._staff("cover@cov.test", "Carl Cover", EdifyRole.CCEO)
        cls.second_cover = cls._staff("cover2@cov.test", "Cora Cover", EdifyRole.CCEO)

    @classmethod
    def _staff(cls, email, name, role):
        user = User.objects.create_user(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            password="x",
            is_active=True,
        )
        return StaffProfile.objects.create(user=user, title=name)

    def assert_refused(self, make, *, why):
        with self.assertRaises(IntegrityError, msg=why):
            with transaction.atomic():
                make()

    def leave(self, *, start="2026-03-02", end="2026-03-06", staff=None):
        return Leave.objects.create(
            staff=staff or self.absent,
            type="personal_time_off",
            start_date=start,
            end_date=end,
            days=5,
            status="approved",
        )

    def coverage(self, leave, **over):
        now = timezone.now()
        fields = {
            "leave_request": leave,
            "original_staff": leave.staff,
            "covering_staff": self.cover,
            "start_datetime": now,
            "end_datetime": now + timedelta(days=4),
            "status": "active",
        }
        fields.update(over)
        return TemporaryCoverageAssignment.objects.create(**fields)


class CoverageConstraintTest(CoverageFixture):
    # ── one active coverage per leave request ────────────────────────────
    def test_a_leave_cannot_delegate_to_two_people_at_once(self):
        leave = self.leave()
        self.coverage(leave)
        self.assert_refused(
            lambda: self.coverage(leave, covering_staff=self.second_cover),
            why="two delegates for one absent person is the ambiguity itself "
            "— every authority check returns both",
        )

    def test_a_revoked_coverage_makes_room_for_its_replacement(self):
        """The reassign path revokes then creates; that must keep working."""
        leave = self.leave()
        first = self.coverage(leave)
        first.status = "revoked"
        first.revoked_at = timezone.now()
        first.save(update_fields=["status", "revoked_at"])

        replacement = self.coverage(leave, covering_staff=self.second_cover)
        self.assertEqual(replacement.covering_staff_id, self.second_cover.id)
        self.assertEqual(
            TemporaryCoverageAssignment.objects.filter(
                leave_request=leave, status="active"
            ).count(),
            1,
        )

    def test_a_leave_may_hold_any_number_of_revoked_coverages(self):
        """History is kept, not deleted — the index only binds active rows."""
        leave = self.leave()
        for _ in range(3):
            self.coverage(leave, status="revoked")
        self.coverage(leave)
        self.assertEqual(
            TemporaryCoverageAssignment.objects.filter(leave_request=leave).count(), 4
        )

    def test_a_later_leave_gets_its_own_coverage_despite_the_stale_status(self):
        """The trap this model sets, and the reason the key is leave_request.

        Nothing ever writes status="expired", so a coverage from a leave two
        years ago still reads "active" forever. Keyed on the covered person
        that stale row would refuse today's legitimate delegation. Keyed on
        the leave request it cannot: a leave is approved once and never
        recurs, so the old row can only ever collide with a second coverage
        on the SAME leave — which is precisely the state being forbidden.
        """
        old_leave = self.leave(start="2024-03-04", end="2024-03-08")
        long_past = timezone.now() - timedelta(days=730)
        stale = self.coverage(
            old_leave,
            start_datetime=long_past,
            end_datetime=long_past + timedelta(days=4),
        )
        self.assertEqual(stale.status, "active")
        self.assertFalse(stale.is_live, "a two-year-old window is not live")

        today_leave = self.leave(start="2026-03-02", end="2026-03-06")
        fresh = self.coverage(today_leave, covering_staff=self.second_cover)

        self.assertTrue(fresh.is_live)
        self.assertEqual(
            TemporaryCoverageAssignment.objects.filter(
                original_staff=self.absent, status="active"
            ).count(),
            2,
            "both rows read active — only one is live, and the constraint "
            "must not confuse the two",
        )

    # ── the window must run forwards ─────────────────────────────────────
    def test_an_inverted_window_is_refused(self):
        leave = self.leave()
        now = timezone.now()
        self.assert_refused(
            lambda: self.coverage(
                leave, start_datetime=now, end_datetime=now - timedelta(hours=1)
            ),
            why="every authority check tests start <= now <= end, so such a "
            "delegation grants nothing while looking live on the page",
        )

    def test_a_zero_length_window_is_accepted(self):
        """Degenerate but unambiguous, so the boundary stays legal — the
        constraint is >=, not >."""
        leave = self.leave()
        instant = timezone.now()
        row = self.coverage(leave, start_datetime=instant, end_datetime=instant)
        self.assertEqual(row.start_datetime, row.end_datetime)

    def test_an_ordinary_forward_window_is_accepted(self):
        leave = self.leave()
        row = self.coverage(leave)
        self.assertLess(row.start_datetime, row.end_datetime)
        self.assertTrue(row.is_live)


class CoverageMigrationPreCheckTest(CoverageFixture):
    """The guards that run BEFORE the DDL in migration 0024.

    Production has had no defence against either state, so both guards have a
    real chance of firing on deploy. When they do, the operator must get the
    leave, the count and an example id — plus, for the duplicate case, the
    remedy, because "delete one" is the wrong answer: the superseded row is
    revoked, never removed.
    """

    def setUp(self):
        import importlib

        from django.apps import apps as app_registry

        self.registry = app_registry
        self.migration = importlib.import_module(
            "apps.accounts.migrations."
            "0024_temporarycoverageassignment_uniq_active_coverage_per_leave_"
            "request_and_more"
        )

    @staticmethod
    def _drop_index():
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX uniq_active_coverage_per_leave_request")

    @staticmethod
    def _drop_check():
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE temporary_coverage_assignment "
                "DROP CONSTRAINT coverage_window_ordered"
            )

    def test_two_active_coverages_name_the_leave_and_a_row(self):
        self._drop_index()
        leave = self.leave()
        first = self.coverage(leave)
        self.coverage(leave, covering_staff=self.second_cover)

        with self.assertRaises(RuntimeError) as caught:
            self.migration.check_one_active_coverage_per_leave(self.registry, None)

        message = str(caught.exception)
        self.assertIn("uniq_active_coverage_per_leave_request", message)
        self.assertIn("temporary_coverage_assignment", message)
        self.assertIn(leave.id, message)
        self.assertIn("has 2 active coverages", message)
        self.assertIn(first.id, message)
        self.assertIn("revoked", message)

    def test_an_inverted_window_names_the_row(self):
        self._drop_check()
        leave = self.leave()
        now = timezone.now()
        bad = self.coverage(
            leave, start_datetime=now, end_datetime=now - timedelta(hours=1)
        )

        with self.assertRaises(RuntimeError) as caught:
            self.migration.check_coverage_windows_ordered(self.registry, None)

        message = str(caught.exception)
        self.assertIn("coverage_window_ordered", message)
        self.assertIn("1 existing row(s) violate it", message)
        self.assertIn(bad.id, message)

    def test_the_stale_active_history_does_not_trip_either_guard(self):
        """The whole point of the leave_request key: a database full of
        never-expired historical grants must migrate cleanly."""
        self._drop_index()
        long_past = timezone.now() - timedelta(days=900)
        for offset in range(4):
            old = self.leave(start="2024-03-04", end="2024-03-08")
            self.coverage(
                old,
                start_datetime=long_past + timedelta(days=offset),
                end_datetime=long_past + timedelta(days=offset + 4),
            )
        self.coverage(self.leave())

        self.migration.check_one_active_coverage_per_leave(self.registry, None)
        self.migration.check_coverage_windows_ordered(self.registry, None)
