"""Database-level money floors on the cost spine (INT-01).

apps/budget declared two unique constraints and zero check constraints, so a
negative rate was a legal row on the rate card that every activity cost in
the platform is multiplied out of.

Each rule is asserted twice. The refusal alone proves nothing: the boundary
here is >= 0 rather than > 0, and a test that only checked -1 would pass
just as happily against a wrong `> 0` constraint that blocked the zero-rate
lines the costing engine is built to produce.
"""

from __future__ import annotations

from datetime import date
from itertools import count

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.activities.models import Activity, ActivityType
from apps.budget.models import (
    BudgetAmendment,
    CostCatalogue,
    CostSetting,
    CostSettingHistory,
    MonthlyFundRequest,
)
from apps.geography.models import District, Region
from apps.schools.models import School

_ids = count(1)


class BudgetFloorTestCase(TestCase):
    def assert_refused(self, make, *, why):
        with self.assertRaises(IntegrityError, msg=why):
            with transaction.atomic():
                make()


class CostSettingFloorTest(BudgetFloorTestCase):
    @classmethod
    def setUpTestData(cls):
        # A distinct FY: the seed migrations already publish an active
        # catalogue for the current one, and colliding with
        # uniq_catalogue_country_fy_version would fail the fixture rather
        # than exercise the constraint under test.
        cls.catalogue = CostCatalogue.objects.create(fy="2099", version=1)

    def _rate(self, unit_cost):
        return CostSetting.objects.create(
            key=f"rate_{next(_ids)}",
            label="Test rate",
            unit_cost=unit_cost,
            fy="2099",
            catalogue=self.catalogue,
        )

    def test_unit_cost_may_not_be_negative(self):
        self.assert_refused(
            lambda: self._rate(-1),
            why="a negative rate propagates a negative amount into every "
            "cost line derived from it",
        )

    def test_unit_cost_of_zero_is_accepted(self):
        """The boundary that makes this >= 0 rather than > 0.

        costing.py distinguishes a MISSING rate (None — the activity is
        flagged costMissing and blocked from funding) from a rate of zero,
        which is a real, priced "no charge" entry.
        """
        self.assertEqual(self._rate(0).unit_cost, 0)


class CostSettingHistoryFloorTest(BudgetFloorTestCase):
    def _history(self, **over):
        fields = {
            "key": f"rate_{next(_ids)}",
            "label": "Test rate",
            "old_unit_cost": 10_000,
            "new_unit_cost": 12_000,
            "version": 2,
            "fy": "2026",
            "changed_by_user_id": "cd-1",
        }
        fields.update(over)
        return CostSettingHistory.objects.create(**fields)

    def test_new_unit_cost_may_not_be_negative(self):
        self.assert_refused(
            lambda: self._history(new_unit_cost=-1),
            why="history must not be able to record a rate the register "
            "itself would reject",
        )

    def test_old_unit_cost_may_not_be_negative(self):
        self.assert_refused(
            lambda: self._history(old_unit_cost=-1), why="same rule, same domain"
        )

    def test_zero_and_null_are_accepted(self):
        """Both halves of the audit twin: zero is a legal rate, and
        old_unit_cost is null on the first create (the field's own comment)."""
        self.assertEqual(self._history(new_unit_cost=0).new_unit_cost, 0)
        self.assertEqual(self._history(old_unit_cost=0).old_unit_cost, 0)
        self.assertIsNone(self._history(old_unit_cost=None).old_unit_cost)


class MonthlyFundRequestFloorTest(BudgetFloorTestCase):
    def _row(self, amount):
        return MonthlyFundRequest.objects.create(
            fy="2026", month=2, staff_id="s-1", amount=amount
        )

    def test_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self._row(-1), why="a request cannot be for negative money"
        )

    def test_amount_of_zero_is_accepted(self):
        self.assertEqual(self._row(0).amount, 0)


class BudgetAmendmentFloorTest(BudgetFloorTestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Amendment Region")
        district = District.objects.create(name="Amendment District", region=region)
        school = School.objects.create(
            school_id="AMD-SCH",
            name="Amendment School",
            region=region,
            district=district,
        )
        cls.activity = Activity.objects.create(
            school=school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            fy="2026",
            quarter="Q2",
            responsible_staff_id="amd-staff-1",
        )

    def _amendment(self, **over):
        fields = {
            "activity": self.activity,
            "new_date": date(2026, 3, 1),
            "original_amount": 250_000,
            "reason": "School closed on the original date.",
            "requested_by": "cceo-1",
        }
        fields.update(over)
        return BudgetAmendment.objects.create(**fields)

    def test_original_amount_may_not_be_negative(self):
        self.assert_refused(
            lambda: self._amendment(original_amount=-1),
            why="the pre-amendment cost is a historical fact, not a credit",
        )

    def test_original_amount_of_zero_is_accepted(self):
        """The field's own `default=0` settles the boundary: zero is the
        documented value for an amendment carrying no cost yet."""
        self.assertEqual(self._amendment(original_amount=0).original_amount, 0)

    def test_moving_an_activity_backwards_is_still_allowed(self):
        """Documents a deliberate non-constraint: the whole point of an
        amendment is to move a date, in either direction."""
        row = self._amendment(original_date=date(2026, 6, 1), new_date=date(2026, 3, 1))
        self.assertLess(row.new_date, row.original_date)


class MigrationPreCheckTest(BudgetFloorTestCase):
    """The guard that runs BEFORE the DDL in migration 0009.

    The dev database is empty, so a green local migration proves nothing
    about production. What must hold is that a violating row produces the
    table, the column, the count and an example id rather than a bare
    Postgres "violated by some row" — and that a clean database passes every
    spec in the table-driven list (a typo in one of those tuples would only
    surface as a LookupError mid-deploy).
    """

    def setUp(self):
        import importlib

        from django.apps import apps as app_registry

        self.registry = app_registry
        self.migration = importlib.import_module(
            "apps.budget.migrations."
            "0009_budgetamendment_budget_amendment_original_amount_non_negative"
            "_and_more"
        )

    def test_every_spec_resolves_and_a_clean_database_passes(self):
        self.migration.check_money_floors(self.registry, None)
        self.assertEqual(len(self.migration._SPECS), 5)

    def test_a_negative_rate_names_the_table_column_count_and_row(self):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE cost_setting DROP CONSTRAINT "
                "cost_setting_unit_cost_non_negative"
            )
        bad = CostSetting.objects.create(
            key="negative_rate", label="Broken rate", unit_cost=-500, fy="2099"
        )

        with self.assertRaises(RuntimeError) as caught:
            self.migration.check_money_floors(self.registry, None)

        message = str(caught.exception)
        self.assertIn("cost_setting_unit_cost_non_negative", message)
        self.assertIn("cost_setting", message)
        self.assertIn("unit_cost", message)
        self.assertIn("1 existing row(s) violate it", message)
        self.assertIn(bad.id, message)
