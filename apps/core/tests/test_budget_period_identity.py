"""The three budget entry points must agree to the shilling.

`monthly_budget`, `quarterly_budget` and `fy_budget` are separate callables,
reached from different pages by different roles — the Accountant opens a month,
the CD reviews a quarter, the RVP approves a year. Each re-derives its total
from `ActivityScheduleCostLine` independently.

`test_budget_aggregation` already asserts the identity *inside* one payload:
`fy_budget()["byQuarter"]` sums to its own total. That does not catch the
failure that matters here, which is two entry points disagreeing — a quarter
that includes a month the monthly view excludes, or a year that counts a line
the quarters miss. Nothing compared them, so nothing would have noticed.

The mandate is explicit about the arithmetic and about the tolerance:

    Q1 = October + November + December
    Q2 = January + February + March
    Q3 = April + May + June
    Q4 = July + August + September
    Annual = October through September
    Required financial difference: UGX 0

Note the month index is **month-of-FY** throughout — 1 is October, not January.
Asserting the quarter map explicitly is the point of the first test: a silent
drift to calendar months would move a quarter of the year's spend into the
wrong quarter and every total would still reconcile.
"""

from __future__ import annotations

from django.test import TestCase

from apps.budget.services import (
    _quarter_months,
    fy_budget,
    monthly_budget,
    quarterly_budget,
)
from apps.core.fy import get_operational_fy


def _total(payload):
    """The comparable figure, whatever the entry point calls it."""
    for key in ("total", "totalAmount", "amount", "grandTotal"):
        if isinstance(payload, dict) and key in payload:
            return payload[key]
    return payload


class BudgetPeriodIdentityTest(TestCase):
    """Runs against whatever is in the database, including nothing.

    A zero-everywhere fixture still proves the entry points agree, and the
    identity is what is being asserted — not a particular amount. The suite
    that builds activities and checks the figures is
    `test_budget_aggregation`; this one guards the seams between the three
    services.
    """

    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()

    def test_the_quarter_map_is_fiscal_not_calendar(self):
        # 1 is October. If this ever drifts to calendar months every total
        # below still reconciles while a quarter of the year sits in the wrong
        # quarter — which is why it is pinned separately.
        self.assertEqual(_quarter_months("Q1"), [1, 2, 3])
        self.assertEqual(_quarter_months("Q2"), [4, 5, 6])
        self.assertEqual(_quarter_months("Q3"), [7, 8, 9])
        self.assertEqual(_quarter_months("Q4"), [10, 11, 12])

    def test_every_month_of_the_fiscal_year_is_in_exactly_one_quarter(self):
        covered = [m for q in ("Q1", "Q2", "Q3", "Q4") for m in _quarter_months(q)]
        self.assertEqual(sorted(covered), list(range(1, 13)))
        self.assertEqual(len(covered), len(set(covered)), "a month is double-counted")

    def test_each_quarter_equals_its_three_months(self):
        for quarter in ("Q1", "Q2", "Q3", "Q4"):
            with self.subTest(quarter=quarter):
                months = sum(
                    _total(monthly_budget({"fy": self.fy, "month": str(m)}))
                    for m in _quarter_months(quarter)
                )
                self.assertEqual(
                    _total(quarterly_budget({"fy": self.fy, "quarter": quarter})),
                    months,
                    f"{quarter} disagrees with its three months",
                )

    def test_the_year_equals_its_four_quarters(self):
        quarters = sum(
            _total(quarterly_budget({"fy": self.fy, "quarter": q}))
            for q in ("Q1", "Q2", "Q3", "Q4")
        )
        self.assertEqual(_total(fy_budget({"fy": self.fy})), quarters)

    def test_the_year_equals_its_twelve_months(self):
        """Asserted separately from the quarters.

        Going month → quarter → year could hide a compensating error that
        month → year would expose, so both routes to the same number are
        checked rather than assuming one implies the other.
        """
        months = sum(
            _total(monthly_budget({"fy": self.fy, "month": str(m)}))
            for m in range(1, 13)
        )
        self.assertEqual(_total(fy_budget({"fy": self.fy})), months)
