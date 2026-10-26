"""A day is Primary, Secondary or Mixed by where its work is.

Owner, 2026-10-12: "make sure that all plans (Trainings, school visits and
field events) in the primary district is marked as Primary district and all
that are in secondary district it is marked as secondary district. Only those
that are crossing from primary to secondary on the same day can be mixed. If
a staff is crossing from secondary district to another secondary district, it
should remain secondary. Again I repeat, crossing from Primary to secondary is
Mixed and it uses secondary district transport cost. Secondary to secondary
remains secondary and fetches secondary costs."
"""

from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase
from freezegun import freeze_time

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.costing_service import preview

from .models import DailyVisitBatch
from .pricing import (
    MIXED_DAY,
    MIXED_TRANSPORT_LABEL,
    PRIMARY_DAY,
    SECONDARY_DAY,
    day_district_mark,
    day_line_label,
    pricing_district_type,
)
from .services import _write_day_lines, batch_needs_repricing
from .tests import PRIMARY_RATES, SECONDARY_RATES, DailyVisitBatchTestCase

PRIMARY_TRANSPORT = dict(PRIMARY_RATES)["primary_transport_per_day"]
SECONDARY_TRANSPORT = dict(SECONDARY_RATES)["secondary_transport_per_day"]
SECONDARY_DAY_TOTAL = sum(dict(SECONDARY_RATES).values())


class DayMarkRuleTest(SimpleTestCase):
    def test_the_three_marks(self):
        self.assertEqual(day_district_mark(["primary"]), PRIMARY_DAY)
        self.assertEqual(day_district_mark(["primary", "primary"]), PRIMARY_DAY)
        self.assertEqual(day_district_mark(["secondary"]), SECONDARY_DAY)
        # Secondary to another secondary remains Secondary.
        self.assertEqual(day_district_mark(["secondary", "secondary"]), SECONDARY_DAY)
        # Only primary with secondary is Mixed, in either order.
        self.assertEqual(day_district_mark(["primary", "secondary"]), MIXED_DAY)
        self.assertEqual(day_district_mark(["secondary", "primary"]), MIXED_DAY)
        # A district nobody classified prices, and counts, as primary.
        self.assertEqual(day_district_mark([None]), PRIMARY_DAY)
        self.assertEqual(day_district_mark([None, "secondary"]), MIXED_DAY)
        self.assertEqual(day_district_mark([]), PRIMARY_DAY)

    def test_a_mixed_day_pays_the_secondary_rates(self):
        self.assertEqual(pricing_district_type(PRIMARY_DAY), "primary")
        self.assertEqual(pricing_district_type(SECONDARY_DAY), "secondary")
        self.assertEqual(pricing_district_type(MIXED_DAY), "secondary")

    def test_only_a_mixed_days_transport_is_renamed(self):
        self.assertEqual(
            day_line_label("secondary_transport_per_day", MIXED_DAY),
            MIXED_TRANSPORT_LABEL,
        )
        self.assertEqual(
            day_line_label("secondary_transport_per_day", SECONDARY_DAY),
            "Transport Secondary District",
        )
        self.assertEqual(
            day_line_label("primary_transport_per_day", PRIMARY_DAY),
            "Transport Primary District",
        )
        self.assertEqual(day_line_label("lunch_per_day", MIXED_DAY), "Lunch")


@freeze_time("2026-07-27")
class DayMarkOnThePlanTest(DailyVisitBatchTestCase):
    def _transport(self, day):
        return list(
            ActivityScheduleCostLine.objects.filter(
                activity__daily_visit_batch__visit_date=day,
                cost_setting_key__endswith="transport_per_day",
            ).order_by("activity_id")
        )

    def test_a_day_in_the_primary_district_is_primary(self):
        day = date(2026, 8, 3)
        self._schedule(["BATCH-P-1", "BATCH-P-2"], day, reason="two")
        lines = self._transport(day)
        self.assertEqual(
            {(line.cost_setting_key, line.label) for line in lines},
            {("primary_transport_per_day", "Transport Primary District")},
        )
        self.assertEqual(sum(line.amount for line in lines), PRIMARY_TRANSPORT)
        self.assertEqual(DailyVisitBatch.objects.get().district_type, "primary")

    def test_secondary_to_secondary_remains_secondary(self):
        day = date(2026, 8, 4)
        result = self._schedule(["BATCH-SEC-A", "BATCH-SEC-B"], day, reason="two")
        lines = self._transport(day)
        self.assertEqual(
            {(line.cost_setting_key, line.label) for line in lines},
            {("secondary_transport_per_day", "Transport Secondary District")},
        )
        self.assertEqual(sum(line.amount for line in lines), SECONDARY_TRANSPORT)
        batch = DailyVisitBatch.objects.get(id=result["batchId"])
        self.assertEqual(batch.district_type, "secondary")
        self.assertEqual(batch.daily_pool_amount, SECONDARY_DAY_TOTAL)
        self.assertFalse(batch_needs_repricing(batch))

    def test_primary_to_secondary_is_mixed_at_the_secondary_rate(self):
        day = date(2026, 8, 5)
        result = self._schedule(["BATCH-P-1", "BATCH-SEC-A"], day, reason="two")
        lines = self._transport(day)
        # Both visits of the day, the one in the primary district included.
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            {(line.cost_setting_key, line.label) for line in lines},
            {("secondary_transport_per_day", MIXED_TRANSPORT_LABEL)},
        )
        self.assertEqual(sum(line.amount for line in lines), SECONDARY_TRANSPORT)
        batch = DailyVisitBatch.objects.get(id=result["batchId"])
        self.assertEqual(batch.district_type, "secondary")
        self.assertEqual(batch.daily_pool_amount, SECONDARY_DAY_TOTAL)
        self.assertFalse(batch_needs_repricing(batch))

    def test_a_day_that_stops_crossing_loses_the_mark(self):
        from apps.activities.services import cancel as cancel_activity

        day = date(2026, 8, 6)
        result = self._schedule(["BATCH-P-1", "BATCH-SEC-A"], day, reason="two")
        primary_visit = Activity.objects.get(
            id__in=[a["id"] for a in result["activities"]],
            school=self.schools["p1"],
        )
        cancel_activity(primary_visit.id, {"reason": "moved"}, self.principal)
        labels = {line.label for line in self._transport(day) if line.amount}
        self.assertEqual(labels, {"Transport Secondary District"})

    def test_a_crossing_day_priced_before_the_mark_is_repriced(self):
        day = date(2026, 8, 7)
        result = self._schedule(["BATCH-P-1", "BATCH-SEC-A"], day, reason="two")
        batch = DailyVisitBatch.objects.get(id=result["batchId"])
        ActivityScheduleCostLine.objects.filter(label=MIXED_TRANSPORT_LABEL).update(
            label="Transport Secondary District"
        )
        self.assertTrue(batch_needs_repricing(batch))
        _write_day_lines(batch, None, batch.responsible_user)
        self.assertFalse(batch_needs_repricing(batch))
        self.assertEqual(
            {line.label for line in self._transport(day)}, {MIXED_TRANSPORT_LABEL}
        )

    def test_the_estimate_prices_a_crossing_day_instead_of_refusing_it(self):
        """Until 2026-10-12 the estimate answered "Choose a separate day for
        primary and secondary district activities" for a day the save
        accepts."""
        day = date(2026, 8, 10)
        self._schedule(["BATCH-P-1"], day, reason="solo")
        result = preview(
            {
                **self.base_fields,
                "schoolId": self.sec_school_a.school_id,
                "plannedDate": day.isoformat(),
            },
            responsible_user_id=self.staff_user.id,
        )
        transport = [
            line
            for line in result["lines"]
            if line["key"].endswith("transport_per_day")
        ]
        self.assertEqual(
            [(line["key"], line["label"]) for line in transport],
            [("secondary_transport_per_day", MIXED_TRANSPORT_LABEL)],
        )
        # Half of the secondary day's transport: two schools share the day.
        self.assertEqual(transport[0]["amount"], SECONDARY_TRANSPORT // 2)

    def test_the_estimate_of_a_second_secondary_district_stays_secondary(self):
        day = date(2026, 8, 11)
        self._schedule(["BATCH-SEC-A"], day, reason="solo")
        result = preview(
            {
                **self.base_fields,
                "schoolId": self.sec_school_b.school_id,
                "plannedDate": day.isoformat(),
            },
            responsible_user_id=self.staff_user.id,
        )
        labels = [
            line["label"]
            for line in result["lines"]
            if line["key"].endswith("transport_per_day")
        ]
        # One transport line, named as the catalogue names the secondary
        # rate, and not marked Mixed.
        self.assertEqual(len(labels), 1)
        self.assertNotEqual(labels[0], MIXED_TRANSPORT_LABEL)


@freeze_time("2026-07-27")
class DistrictTypeColumnTest(DailyVisitBatchTestCase):
    """The District Type every table and export shows (owner, 2026-10-12:
    "Add District and district type column ... literally on all the tables
    and in all exports")."""

    def _labels(self, result):
        from .district_marks import district_type_labels

        ids = [a["id"] for a in result["activities"]]
        by_school = dict(
            Activity.objects.filter(id__in=ids).values_list("school__school_id", "id")
        )
        labels = district_type_labels(ids)
        return {code: labels[pk] for code, pk in by_school.items()}

    def test_primary_secondary_and_mixed_days(self):
        primary = self._schedule(["BATCH-P-1", "BATCH-P-2"], date(2026, 8, 3), "two")
        self.assertEqual(
            self._labels(primary),
            {"BATCH-P-1": "Primary District", "BATCH-P-2": "Primary District"},
        )
        secondary = self._schedule(["BATCH-SEC-A"], date(2026, 8, 4), "one")
        self.assertEqual(self._labels(secondary), {"BATCH-SEC-A": "Secondary District"})
        mixed = self._schedule(["BATCH-P-3", "BATCH-SEC-B"], date(2026, 8, 5), "two")
        # Both visits of a crossing day, the one at home included.
        self.assertEqual(
            self._labels(mixed), {"BATCH-P-3": "Mixed", "BATCH-SEC-B": "Mixed"}
        )

    def test_the_lookup_does_not_grow_with_the_rows(self):
        from .district_marks import district_type_labels

        result = self._schedule(
            ["BATCH-P-1", "BATCH-P-2", "BATCH-P-3"], date(2026, 8, 6), "x"
        )
        ids = [a["id"] for a in result["activities"]]
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as one:
            district_type_labels(ids[:1])
        with CaptureQueriesContext(connection) as three:
            self.assertEqual(len(district_type_labels(ids)), 3)
        # A table asks once for all its rows; three rows cost what one does.
        self.assertLessEqual(len(three), len(one))
        self.assertLessEqual(len(one), 8)

    def test_my_plan_shows_the_column_and_exports_it(self):
        import csv
        import io

        from apps.my_plan import table_export

        self._schedule(["BATCH-P-1", "BATCH-SEC-A"], date(2026, 8, 5), "two")
        self.client.force_login(self.staff_user)
        html = self.client.get("/my-plan/", {"fy": "2026", "period": "fy"}).content
        html = html.decode()
        self.assertIn(">District Type</th>", html)
        self.assertIn("data-district-type>Mixed</td>", html)
        # (CSV here: openpyxl cannot write a date while the clock is frozen.)
        response = self.client.get(
            "/my-plan/", {"fy": "2026", "period": "fy", "export": "csv"}
        )
        tables = table_export.tables_from_csv(
            csv.reader(io.StringIO(response.content.decode()))
        )
        visits = tables["School Visits"]
        self.assertEqual(len(visits), 2)
        self.assertEqual({row["District Type"] for row in visits}, {"Mixed"})
        self.assertTrue(all(row["District"] for row in visits))
