"""A table refresh on Planning renders the rows, and computes only the rows.

The list refreshes itself after every save (`planning-saved`), on every filter
change and on every search keystroke, and each refresh swaps
partials/planning/school_table.html alone. It used to build the whole page
first — the KPI strip's twenty queries over the portfolio, the Staff filter's
owner groups — and throw them away: a refresh cost as much as the page
(2026-09-28, "even loading is very slow").
"""

from __future__ import annotations

from unittest import mock

from apps.core.fy import get_operational_fy
from apps.core.metrics import render_precomputed_metric_item
from apps.planning.planning_service import PlanningDashboardService
from apps.planning.test_owner_grouping import OwnerGroupingFixture

TABLE_ONLY = {"HTTP_HX_REQUEST": "true", "HTTP_HX_TARGET": "schools-table-container"}


class TableRefreshSkipsTheSummaryTest(OwnerGroupingFixture):
    def _filters(self):
        return {"fy": get_operational_fy(), "tab": "client", "page": 1, "per_page": 50}

    def test_the_rows_are_the_same_without_the_summary(self):
        full = PlanningDashboardService.get_dashboard_data(
            self.ia_user, self._filters()
        )
        rows = PlanningDashboardService.get_dashboard_data(
            self.ia_user, self._filters(), summary=False
        )
        names = [s["name"] for s in full["schools"]]
        self.assertIn("Apple Primary", names)
        self.assertEqual([s["name"] for s in rows["schools"]], names)
        self.assertEqual(rows["total_count"], full["total_count"])
        self.assertEqual(rows["total_pages"], full["total_pages"])
        self.assertTrue(full["kpi_strip_items"])
        self.assertEqual(rows["kpi_strip_items"], [])

    def _strip_calls(self, **headers):
        with mock.patch(
            "apps.planning.planning_service.render_precomputed_metric_item",
            wraps=render_precomputed_metric_item,
        ) as strip:
            response = self.client.get("/planning", **headers)
        self.assertEqual(response.status_code, 200)
        return response, strip.call_count

    def test_a_table_refresh_builds_no_kpi_strip(self):
        self.client.force_login(self.ia_user)
        response, calls = self._strip_calls(**TABLE_ONLY)
        self.assertEqual(calls, 0)
        self.assertContains(response, "Apple Primary")
        self.assertContains(response, "Zebra Primary")

    def test_the_page_still_builds_it(self):
        self.client.force_login(self.ia_user)
        response, calls = self._strip_calls()
        self.assertGreater(calls, 0)
        self.assertContains(response, "Planning context")
