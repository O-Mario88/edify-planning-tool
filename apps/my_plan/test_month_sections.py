"""My Plan is a year read a month at a time, October through next September.

Owner, 2026-09-16: "remove the weekly view and just display all the plans, just
arrange the dates by month (October dates, November dates, … until next
September)" — for the School Visit, Cluster Training and Cluster Meeting cards.

The week was the default slice, so opening My Plan answered "what is on this
week" and nothing else; the shape of a year was fifty-two clicks away. These
pin what replaced it: the fiscal year's own month order, every row filed under
the month it falls in, and nothing dropped on the way.
"""

from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase

from apps.my_plan.services import (
    UNDATED_MONTH_KEY,
    fy_calendar_year,
    fy_months,
    month_sections,
    month_summary,
)


def _row(day, **extra):
    return {"id": extra.pop("id", f"a-{day}"), "planned_date": day, **extra}


class FiscalMonthOrderTests(SimpleTestCase):
    def test_the_year_starts_in_october_and_ends_next_september(self):
        months = fy_months("2026")

        self.assertEqual(len(months), 12)
        self.assertEqual(
            [m["month"] for m in months], [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        )
        self.assertEqual(months[0]["label"], "October 2025")
        self.assertEqual(months[-1]["label"], "September 2026")

    def test_october_belongs_to_the_previous_calendar_year(self):
        """FY2026 runs 1 October 2025 → 30 September 2026. A January heading
        that read 2025 would file three months of work under the wrong year."""
        self.assertEqual(fy_calendar_year("2026", 10), 2025)
        self.assertEqual(fy_calendar_year("2026", 12), 2025)
        self.assertEqual(fy_calendar_year("2026", 1), 2026)
        self.assertEqual(fy_calendar_year("2026", 9), 2026)

    def test_the_current_month_is_marked_once(self):
        months = fy_months("2026", today=date(2026, 2, 11))
        current = [m for m in months if m["is_current"]]

        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["label"], "February 2026")


class MonthSectionTests(SimpleTestCase):
    def test_rows_are_filed_under_their_month_in_fiscal_order(self):
        rows = [
            _row(date(2026, 1, 9), id="jan"),
            _row(date(2025, 10, 2), id="oct"),
            _row(date(2026, 9, 30), id="sep"),
            _row(date(2025, 10, 28), id="oct-2"),
        ]

        sections = month_sections(rows, fy="2026", today=date(2025, 10, 15))

        self.assertEqual(
            [s["label"] for s in sections],
            ["October 2025", "January 2026", "September 2026"],
        )
        self.assertEqual([r["id"] for r in sections[0]["rows"]], ["oct", "oct-2"])
        self.assertEqual(sections[0]["count"], 2)

    def test_a_month_with_nothing_in_it_is_not_an_empty_heading(self):
        sections = month_sections([_row(date(2026, 3, 4))], fy="2026")

        self.assertEqual([s["label"] for s in sections], ["March 2026"])

    def test_an_undated_row_keeps_its_place_at_the_end(self):
        """An activity waiting on a date is still the person's work. Filing it
        nowhere is how a plan quietly loses rows."""
        sections = month_sections(
            [_row(None, id="tbc"), _row(date(2025, 11, 3), id="nov")], fy="2026"
        )

        self.assertEqual([s["key"] for s in sections], ["2025-11", UNDATED_MONTH_KEY])
        self.assertEqual(sections[-1]["label"], "No date yet")
        self.assertEqual([r["id"] for r in sections[-1]["rows"]], ["tbc"])

    def test_a_date_outside_the_fiscal_year_still_gets_a_month(self):
        """A carried-over or mis-dated row is surfaced under its own month
        rather than dropped between the twelve and the bottom of the card."""
        sections = month_sections(
            [_row(date(2026, 11, 2), id="next-fy"), _row(date(2026, 5, 6), id="may")],
            fy="2026",
        )

        self.assertEqual([s["label"] for s in sections], ["May 2026", "November 2026"])

    def test_every_row_survives_the_grouping(self):
        rows = [_row(date(2026, month, 1), id=str(month)) for month in range(1, 10)]
        rows += [_row(date(2025, month, 1), id=f"p{month}") for month in (10, 11, 12)]
        rows += [_row(None, id="tbc")]

        sections = month_sections(rows, fy="2026")

        self.assertEqual(sum(s["count"] for s in sections), len(rows))
        self.assertEqual(
            {r["id"] for s in sections for r in s["rows"]}, {r["id"] for r in rows}
        )


class MonthSummaryTests(SimpleTestCase):
    def test_an_empty_month_reads_zero_rather_than_disappearing(self):
        """The strip's job is the shape of the year, and a month with nothing
        planned in it is the part a supervisor most needs to see."""
        summary = month_summary(
            "2026",
            [_row(date(2025, 10, 6))],
            [_row(date(2026, 4, 2)), _row(date(2026, 4, 9))],
            today=date(2025, 10, 15),
        )

        self.assertEqual(len(summary), 12)
        counts = {m["label"]: m["count"] for m in summary}
        self.assertEqual(counts["October 2025"], 1)
        self.assertEqual(counts["April 2026"], 2)
        self.assertEqual(counts["February 2026"], 0)

    def test_the_strip_counts_every_card_together(self):
        summary = month_summary(
            "2026",
            [_row(date(2025, 12, 1))],
            [_row(date(2025, 12, 2))],
            [_row(date(2025, 12, 3))],
            [],
        )

        self.assertEqual(next(m["count"] for m in summary if m["key"] == "2025-12"), 3)

    def test_undated_work_is_reported_not_swallowed(self):
        summary = month_summary("2026", [_row(None), _row(None)])

        self.assertEqual(summary[-1]["key"], UNDATED_MONTH_KEY)
        self.assertEqual(summary[-1]["count"], 2)

    def test_no_undated_work_adds_no_thirteenth_column(self):
        summary = month_summary("2026", [_row(date(2026, 6, 6))])

        self.assertEqual(len(summary), 12)
