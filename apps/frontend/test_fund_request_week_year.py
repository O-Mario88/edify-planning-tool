"""A Fund Requests page reads the year of the week it is asked for (2026-09-28).

A weekly request is filed under the year of its Monday
(apps.fund_requests.weekly_service). Asked for a week from 1 October onward
with no year, the page read the running year and found no request — the PL's
accountability approval included — until the year rolled over.
"""

from __future__ import annotations

from django.test import RequestFactory, SimpleTestCase
from freezegun import freeze_time

from apps.frontend.views.budget_views import _page_fy


class FundRequestPageYearTest(SimpleTestCase):
    def _fy(self, **params):
        return _page_fy(RequestFactory().get("/fund-requests/weekly", params))

    @freeze_time("2026-09-28 09:00:00")
    def test_a_week_in_the_next_year_reads_that_year(self):
        self.assertEqual(self._fy(week="2026-10-05"), "2027")
        # Any day of the week names it; the week's Monday decides the year.
        self.assertEqual(self._fy(week="2026-10-07"), "2027")

    @freeze_time("2026-09-28 09:00:00")
    def test_a_week_that_starts_in_september_stays_in_that_year(self):
        self.assertEqual(self._fy(week="2026-10-02"), "2026")

    @freeze_time("2026-09-28 09:00:00")
    def test_an_explicit_year_wins_and_no_week_reads_the_running_year(self):
        self.assertEqual(self._fy(week="2026-10-05", fy="2026"), "2026")
        self.assertEqual(self._fy(), "2026")
        self.assertEqual(self._fy(week="not-a-date"), "2026")
