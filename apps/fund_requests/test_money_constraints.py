"""Database-level money floors on the fund-request tables (INT-01), and the
NetSuite-Code uniqueness that finance clearance depends on (INTG-07).

These tests are about what POSTGRES refuses, not what a service refuses. The
services already bound these figures; the audit's point was that a management
command, an import, a repair script or a shell bypasses every one of them and
the database accepted a negative disbursement without complaint.

Each rule is asserted twice on purpose. Proving the database rejects -1 shows
nothing on its own — a constraint that also rejected the legitimate boundary
would pass that half and quietly break real work. So every case pairs the
refusal with the boundary value that MUST still be accepted, and the boundary
is different per column: a returned_amount of 0 is an ordinary outcome, while
a reimbursed_amount of 0 records a payment that never happened.
"""

from __future__ import annotations

from datetime import date, timedelta
from itertools import count

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.activities.models import Activity, ActivityScheduleCostLine, ActivityType
from apps.fund_requests.models import (
    AdvanceRequest,
    AdvanceRequestStatus,
    FundRequest,
    FundRequestItem,
    FundRequestPeriod,
    WeeklyFundRequest,
)
from apps.geography.models import District, Region
from apps.schools.models import School

_ids = count(1)


class MoneyFloorTestCase(TestCase):
    """Shared helpers: every factory below hands back a row that satisfies
    the table's pre-existing unique constraints, so a failure can only ever
    be the check constraint under test."""

    def assert_refused(self, make, *, why):
        """The database must reject this row.

        Wrapped in an inner atomic block: a failed statement poisons the
        surrounding transaction, and the test needs to keep using it.
        """
        with self.assertRaises(IntegrityError, msg=why):
            with transaction.atomic():
                make()

    # ── factories ────────────────────────────────────────────────────────
    def fund_request(self, **over):
        fields = {
            "fy": "2026",
            "period": FundRequestPeriod.MONTHLY,
            "period_key": "2026-M2",
            "scope": "own",
            # Unique per row: uniq_request_period_owner would otherwise be
            # the thing that fails and the test would prove nothing.
            "submitted_by_user_id": f"u-{next(_ids)}",
            "submitted_by_role": "CCEO",
            "total_amount": 100_000,
            "activity_count": 1,
        }
        fields.update(over)
        return FundRequest.objects.create(**fields)

    def weekly_request(self, **over):
        fields = {
            "fy": "2026",
            "week_start_date": date(2026, 2, 2),
            "week_end_date": date(2026, 2, 8),
            "responsible_user": f"u-{next(_ids)}",
            "total_amount": 100_000,
        }
        fields.update(over)
        return WeeklyFundRequest.objects.create(**fields)


class FundRequestMoneyFloorsTest(MoneyFloorTestCase):
    def test_total_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self.fund_request(total_amount=-1),
            why="a request cannot ask for a negative sum of money",
        )

    def test_total_amount_of_zero_is_accepted(self):
        """Not > 0: total_amount sums the period's cost lines, and
        apps/budget/costing.py prices a line at 0 when its rate is missing or
        its quantity is zero, so a zero total is reachable and legitimate."""
        self.assertEqual(self.fund_request(total_amount=0).total_amount, 0)

    def test_disbursed_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self.fund_request(disbursed_amount=-50_000),
            why="money cannot leave the account in reverse",
        )

    def test_disbursed_amount_of_zero_and_null_are_accepted(self):
        self.assertEqual(self.fund_request(disbursed_amount=0).disbursed_amount, 0)
        self.assertIsNone(self.fund_request().disbursed_amount)

    def test_accounted_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self.fund_request(accounted_amount=-1),
            why="a negative spend is not a spend",
        )

    def test_accounted_amount_of_zero_is_accepted(self):
        """A full return legitimately accounts for nothing spent —
        accounted == disbursed - returned + reimbursed holds at zero."""
        self.assertEqual(self.fund_request(accounted_amount=0).accounted_amount, 0)

    def test_returned_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self.fund_request(returned_amount=-1),
            why="a negative return would be a second disbursement in disguise",
        )

    def test_returned_amount_of_zero_is_accepted(self):
        """Returning nothing is the ordinary outcome of an exact spend."""
        self.assertEqual(self.fund_request(returned_amount=0).returned_amount, 0)


class FundRequestItemMoneyFloorTest(MoneyFloorTestCase):
    def setUp(self):
        self.request = self.fund_request()

    def _item(self, amount):
        return FundRequestItem.objects.create(
            fund_request=self.request,
            activity_id=f"act-{next(_ids)}",
            activity_schedule_cost_line_id=f"line-{next(_ids)}",
            amount=amount,
            period=FundRequestPeriod.MONTHLY,
            period_key="2026-M2",
        )

    def test_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self._item(-1), why="a cost line cannot cost less than nothing"
        )

    def test_amount_of_zero_is_accepted(self):
        """A line whose rate is missing is priced at 0 by the costing engine
        — a real, requestable line, not a malformed one."""
        self.assertEqual(self._item(0).amount, 0)


class WeeklyFundRequestMoneyFloorsTest(MoneyFloorTestCase):
    def test_total_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self.weekly_request(total_amount=-1),
            why="the weekly channel is money too",
        )

    def test_total_amount_of_zero_is_accepted(self):
        self.assertEqual(self.weekly_request(total_amount=0).total_amount, 0)

    def test_settlement_amounts_may_not_be_negative(self):
        for column in ("disbursed_amount", "accounted_amount", "returned_amount"):
            with self.subTest(column=column):
                self.assert_refused(
                    lambda col=column: self.weekly_request(**{col: -1}),
                    why=f"{column} rolls up child advances and cannot go negative",
                )

    def test_settlement_amounts_of_zero_are_accepted(self):
        for column in ("disbursed_amount", "accounted_amount", "returned_amount"):
            with self.subTest(column=column):
                row = self.weekly_request(**{column: 0})
                self.assertEqual(getattr(row, column), 0)


class AdvanceRequestFixture(MoneyFloorTestCase):
    """AdvanceRequest mirrors exactly one budget line, so every row needs its
    own cost line (uniq_advance_per_budget_line)."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Constraint Region")
        district = District.objects.create(name="Constraint District", region=region)
        cls.school = School.objects.create(
            school_id="CON-SCH",
            name="Constraint School",
            region=region,
            district=district,
        )
        cls.activity = Activity.objects.create(
            school=cls.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            fy="2026",
            quarter="Q2",
            responsible_staff_id="con-staff-1",
        )

    def advance(self, **over):
        line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            # Distinct per line: the activities app already enforces one cost
            # component per key per activity, and a collision there would
            # mask the constraint actually under test.
            cost_setting_key=f"transport_allowance_{next(_ids)}",
            label="Transport",
            unit_cost=50_000,
            quantity=1,
            amount=50_000,
        )
        fields = {
            "activity": self.activity,
            "budget_line": line,
            "responsible_user_id": "con-staff-1",
            "fy": "2026",
            "quarter": "Q2",
            "amount": 50_000,
        }
        fields.update(over)
        return AdvanceRequest.objects.create(**fields)


class AdvanceRequestMoneyFloorsTest(AdvanceRequestFixture):
    def test_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self.advance(amount=-1),
            why="the shared advance ledger feeds every budget rollup",
        )

    def test_amount_of_zero_is_accepted(self):
        self.assertEqual(self.advance(amount=0).amount, 0)

    def test_disbursed_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self.advance(disbursed_amount=-1),
            why="a negative disbursement is the headline finding of INT-01",
        )

    def test_disbursed_amount_of_zero_is_accepted(self):
        """The boundary that makes this >= 0 and not > 0.

        weekly_service.disburse() splits a partial week's disbursement across
        its advances by largest remainder, and finance_services scales the
        legacy path by a rounded fraction — both legitimately allot 0 to a
        line. A `> 0` floor would reject a correct split.
        """
        self.assertEqual(self.advance(disbursed_amount=0).disbursed_amount, 0)

    def test_accounted_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self.advance(accounted_amount=-1),
            why="a negative spend cannot reconcile against anything",
        )

    def test_accounted_amount_of_zero_is_accepted(self):
        self.assertEqual(self.advance(accounted_amount=0).accounted_amount, 0)

    def test_returned_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self.advance(returned_amount=-1),
            why="a negative return is money moving the wrong way",
        )

    def test_returned_amount_of_zero_is_accepted(self):
        """0 is normal here: most advances return nothing."""
        self.assertEqual(self.advance(returned_amount=0).returned_amount, 0)

    def test_reimbursed_amount_may_not_be_negative_or_zero(self):
        """The one > 0 floor in this app, and the reason it differs.

        advance_service.reimburse() refuses to pay unless the amount due is
        strictly positive and the payout equals it exactly. A stored 0 would
        record a payment that never happened while moving the advance into
        REIMBURSEMENT_DISBURSED — a state whose only exit is the employee
        confirming receipt of money they never got.
        """
        for bad in (-1, 0):
            with self.subTest(amount=bad):
                self.assert_refused(
                    lambda value=bad: self.advance(reimbursed_amount=value),
                    why="a reimbursement of zero is not a reimbursement",
                )

    def test_reimbursed_amount_of_one_and_null_are_accepted(self):
        self.assertEqual(self.advance(reimbursed_amount=1).reimbursed_amount, 1)
        # Null is the common case — most advances are never reimbursed.
        self.assertIsNone(self.advance().reimbursed_amount)


class AdvanceNetSuiteIdUniquenessTest(AdvanceRequestFixture):
    """INTG-07. approve_accountability() clears an advance on this field
    merely being non-empty, so without uniqueness one NetSuite expense
    reference satisfied that gate on unlimited advances."""

    def test_one_netsuite_code_cannot_clear_two_advances(self):
        self.advance(
            accountability_netsuite_id="NS-4471",
            status=AdvanceRequestStatus.ACCOUNTABILITY_PENDING,
        )
        self.assert_refused(
            lambda: self.advance(
                accountability_netsuite_id="NS-4471",
                status=AdvanceRequestStatus.ACCOUNTABILITY_PENDING,
            ),
            why="the finance gate would treat both as accounted for",
        )

    def test_distinct_netsuite_codes_are_accepted(self):
        self.advance(accountability_netsuite_id="NS-0001")
        second = self.advance(accountability_netsuite_id="NS-0002")
        self.assertEqual(second.accountability_netsuite_id, "NS-0002")

    def test_many_advances_may_carry_no_code(self):
        """The index is partial for this reason: the great majority of
        advances legitimately have no NetSuite Code — not yet accounted,
        self-funded, cancelled — and both spellings of "absent" occur."""
        self.advance(accountability_netsuite_id=None)
        self.advance(accountability_netsuite_id=None)
        self.advance(accountability_netsuite_id="")
        self.advance(accountability_netsuite_id="")
        self.assertEqual(
            AdvanceRequest.objects.filter(
                accountability_netsuite_id__isnull=True
            ).count(),
            2,
        )
        self.assertEqual(
            AdvanceRequest.objects.filter(accountability_netsuite_id="").count(), 2
        )

    def test_a_code_is_freed_when_its_advance_is_deleted(self):
        """There is no soft delete on this table — advance_service
        .sync_for_activity hard-deletes advances whose budget line went away —
        so a re-used reference must become available again."""
        first = self.advance(accountability_netsuite_id="NS-REUSE")
        first.delete()
        again = self.advance(accountability_netsuite_id="NS-REUSE")
        self.assertEqual(again.accountability_netsuite_id, "NS-REUSE")


class WeeklyNetSuiteRollUpIsNotConstrainedTest(MoneyFloorTestCase):
    """Documents a deliberate non-constraint.

    WeeklyFundRequest.accountability_netsuite_id is a comma-joined LIST of
    its child advances' codes (disbursement_dashboard_service), not an
    identifier. Two weeks may legitimately name the same child code, so
    uniqueness here would be wrong.
    """

    def test_two_weeks_may_carry_the_same_rolled_up_code(self):
        first = self.weekly_request(accountability_netsuite_id="NS-1, NS-2")
        second = self.weekly_request(
            week_start_date=first.week_start_date + timedelta(days=7),
            week_end_date=first.week_end_date + timedelta(days=7),
            accountability_netsuite_id="NS-1, NS-2",
        )
        self.assertEqual(second.accountability_netsuite_id, "NS-1, NS-2")


class MigrationPreCheckTest(AdvanceRequestFixture):
    """The guards that run BEFORE the DDL in migration 0016.

    Worth testing directly, because they only ever run on databases this
    suite does not have: the dev database is empty, so a green local
    migration proves nothing about production. What must be true is that
    when a violating row DOES exist, the operator gets the table, the
    column, the count and an example id instead of a bare Postgres
    "violated by some row".

    Each test drops the constraint, writes the row it forbids, and calls the
    guard. The surrounding TestCase transaction rolls the DDL back — Postgres
    DDL is transactional — so the constraint is restored either way.
    """

    def setUp(self):
        import importlib

        from django.apps import apps as app_registry

        self.registry = app_registry
        self.migration = importlib.import_module(
            "apps.fund_requests.migrations."
            "0016_advancerequest_advance_request_amount_non_negative_and_more"
        )

    @staticmethod
    def _drop(table, constraint):
        """A CheckConstraint is a table constraint; a PARTIAL UniqueConstraint
        is created as a plain unique index and has to be dropped as one."""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")

    @staticmethod
    def _drop_index(name):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(f"DROP INDEX {name}")

    def test_a_negative_amount_names_the_table_column_count_and_row(self):
        self._drop("fund_request", "fund_request_total_amount_non_negative")
        bad = self.fund_request(total_amount=-9_000)

        with self.assertRaises(RuntimeError) as caught:
            self.migration.check_money_floors(self.registry, None)

        message = str(caught.exception)
        self.assertIn("fund_request_total_amount_non_negative", message)
        self.assertIn("fund_request", message)
        self.assertIn("total_amount", message)
        self.assertIn("1 existing row(s) violate it", message)
        self.assertIn(bad.id, message)
        self.assertIn("SELECT id, total_amount FROM fund_request", message)

    def test_a_clean_database_passes_both_guards(self):
        self.advance(accountability_netsuite_id="NS-CLEAN")
        self.fund_request(total_amount=0, returned_amount=0)
        self.migration.check_money_floors(self.registry, None)
        self.migration.check_netsuite_ids_unique(self.registry, None)

    def test_a_shared_netsuite_code_names_the_code_and_an_advance(self):
        self._drop_index("uniq_advance_accountability_netsuite_id")
        first = self.advance(accountability_netsuite_id="NS-SHARED")
        self.advance(accountability_netsuite_id="NS-SHARED")

        with self.assertRaises(RuntimeError) as caught:
            self.migration.check_netsuite_ids_unique(self.registry, None)

        message = str(caught.exception)
        self.assertIn("uniq_advance_accountability_netsuite_id", message)
        self.assertIn("NS-SHARED", message)
        self.assertIn("is on 2 advances", message)
        self.assertIn(first.id, message)

    def test_blank_codes_are_not_reported_as_duplicates(self):
        """The guard must match the index predicate exactly, or it would
        abort a deploy over rows the index would happily accept."""
        self._drop_index("uniq_advance_accountability_netsuite_id")
        self.advance(accountability_netsuite_id="")
        self.advance(accountability_netsuite_id="")
        self.advance(accountability_netsuite_id=None)
        self.advance(accountability_netsuite_id=None)
        self.migration.check_netsuite_ids_unique(self.registry, None)
