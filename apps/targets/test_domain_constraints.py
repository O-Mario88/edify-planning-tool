"""Database-level domains on the personal-target tables (INT-01).

apps/targets declared two unique constraints and zero check constraints. The
three domains pinned here were each already stated in the models and enforced
nowhere, and a row outside one of them does not fail loudly — it stops being
counted. A month_of_fy of 0 or 13 is invisible to every quarter and FY
roll-up that derives its period from the number.

Each rule is asserted twice, because the boundaries are the interesting part:
a target of 0 is legitimate (the phasing assigns it to months a commitment
does not land in) while a weight of 101 is not.
"""

from __future__ import annotations

from itertools import count

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.targets.models import MonthlyPersonalTarget, TargetAdjustment, TargetArea

_ids = count(1)


class TargetDomainTestCase(TestCase):
    def assert_refused(self, make, *, why):
        with self.assertRaises(IntegrityError, msg=why):
            with transaction.atomic():
                make()

    def area(self, **over):
        fields = {
            "key": f"area_{next(_ids)}",
            "label": "School Visits",
            "weight": 20,
        }
        fields.update(over)
        return TargetArea.objects.create(**fields)


class TargetAreaWeightTest(TargetDomainTestCase):
    def test_weight_may_not_be_negative(self):
        self.assert_refused(
            lambda: self.area(weight=-1),
            why="a negative weight SUBTRACTS an area's achievement from "
            "Overall Progress",
        )

    def test_weight_may_not_exceed_one_hundred(self):
        self.assert_refused(
            lambda: self.area(weight=101),
            why="weight is a percent share of a total that must be 100",
        )

    def test_both_ends_of_the_range_are_accepted(self):
        """0 is meaningful — an area tracked but not counted toward the
        weighted score — and 100 is a single area carrying the whole board."""
        self.assertEqual(self.area(weight=0).weight, 0)
        self.assertEqual(self.area(weight=100).weight, 100)


class MonthlyPersonalTargetDomainTest(TargetDomainTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.target_area = TargetArea.objects.create(
            key="mpt_area", label="School Visits", weight=20
        )

    def _target(self, **over):
        fields = {
            "user_id": f"u-{next(_ids)}",
            "area": self.target_area,
            "fy": "2026",
            "month_of_fy": 1,
            "target": 4,
        }
        fields.update(over)
        return MonthlyPersonalTarget.objects.create(**fields)

    def test_month_outside_one_to_twelve_is_refused(self):
        for bad in (0, 13, -1):
            with self.subTest(month_of_fy=bad):
                self.assert_refused(
                    lambda value=bad: self._target(month_of_fy=value),
                    why="an out-of-range month is invisible to every "
                    "quarter and FY roll-up",
                )

    def test_both_ends_of_the_fiscal_year_are_accepted(self):
        """1 = October and 12 = September, per the field's own comment."""
        self.assertEqual(self._target(month_of_fy=1).month_of_fy, 1)
        self.assertEqual(self._target(month_of_fy=12).month_of_fy, 12)

    def test_target_may_not_be_negative(self):
        self.assert_refused(
            lambda: self._target(target=-1),
            why="a negative target makes achievement percentages nonsense",
        )

    def test_target_of_zero_is_accepted(self):
        """The boundary that makes this >= 0 rather than > 0: the
        largest-remainder phasing in hr/performance_engine.py assigns 0 to
        months a commitment does not land in, and `default=0` means
        "no target set"."""
        self.assertEqual(self._target(target=0).target, 0)


class TargetAdjustmentDomainTest(TargetDomainTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.target_area = TargetArea.objects.create(
            key="adj_area", label="School Visits", weight=20
        )

    def _adjustment(self, **over):
        fields = {
            "user_id": f"u-{next(_ids)}",
            "area": self.target_area,
            "fy": "2026",
            "month_of_fy": 3,
            "old_target": 4,
            "new_target": 6,
            "reason": "Reduced portfolio after a school transfer.",
            "requested_by": "pl-1",
        }
        fields.update(over)
        return TargetAdjustment.objects.create(**fields)

    def test_negative_values_are_refused(self):
        for column in ("old_target", "new_target"):
            with self.subTest(column=column):
                self.assert_refused(
                    lambda col=column: self._adjustment(**{col: -1}),
                    why=f"{column} records a MonthlyPersonalTarget value and "
                    "must accept exactly that field's domain",
                )

    def test_month_outside_one_to_twelve_is_refused(self):
        self.assert_refused(
            lambda: self._adjustment(month_of_fy=13),
            why="the audit twin shares the fiscal-month domain",
        )

    def test_zero_values_and_boundary_months_are_accepted(self):
        """A target legitimately moves to or from zero, and the audit record
        must be able to say so — otherwise a legal change becomes an
        unrecordable one."""
        row = self._adjustment(old_target=0, new_target=0, month_of_fy=12)
        self.assertEqual((row.old_target, row.new_target, row.month_of_fy), (0, 0, 12))


class MigrationPreCheckTest(TargetDomainTestCase):
    """The guard that runs BEFORE the DDL in migration 0005.

    Same reasoning as the money migrations: the dev database is empty, so the
    only thing worth asserting locally is that a violating row is reported
    with enough detail to fix it, and that every spec in the table-driven
    list resolves against the real app registry.
    """

    def setUp(self):
        import importlib

        from django.apps import apps as app_registry

        self.registry = app_registry
        self.migration = importlib.import_module(
            "apps.targets.migrations."
            "0005_monthlypersonaltarget_monthly_personal_target_month_1_12"
            "_and_more"
        )

    def test_every_spec_resolves_and_a_clean_database_passes(self):
        self.area(weight=0)
        self.area(weight=100)
        self.migration.check_target_domains(self.registry, None)
        self.assertEqual(len(self.migration._SPECS), 5)

    def test_an_out_of_range_weight_names_the_table_column_count_and_row(self):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE target_area DROP CONSTRAINT target_area_weight_0_100"
            )
        bad = self.area(weight=140)

        with self.assertRaises(RuntimeError) as caught:
            self.migration.check_target_domains(self.registry, None)

        message = str(caught.exception)
        self.assertIn("target_area_weight_0_100", message)
        self.assertIn("target_area", message)
        self.assertIn("weight", message)
        self.assertIn("1 existing row(s) violate it", message)
        self.assertIn(bad.id, message)
