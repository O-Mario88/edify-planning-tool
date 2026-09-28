"""The Work Plan opens on the year being planned (owner, 2026-09-28).

"we want the work plan for next FY that is fy27 populated since people have
already planned for next FY." Once the next fiscal year is open for planning
(its FiscalYearPlanningPolicy row, apps.planning.fy_policy), the Work Plan
opens on it; the year still running is one choice away in the selector. The
Uganda FY2027 row opens planning on 15 September 2026 (planning migration
0011), so the dates below read that row.
"""

from __future__ import annotations

from django.test import TestCase
from freezegun import freeze_time

from apps.accounts.models import User
from apps.core.rbac import EdifyRole
from apps.frontend.views.work_plan_page import build_work_plan_context


class WorkPlanOpensOnThePlanningYearTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="workplan-year@edify.org",
            name="Work Plan Year",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="x",
            is_active=True,
        )

    def _context(self, when, **params):
        with freeze_time(when):
            return build_work_plan_context(self.user, params)

    def test_it_opens_on_next_year_once_that_year_is_open_for_planning(self):
        context = self._context("2026-09-28 09:00:00")
        self.assertEqual(context["fy"], "2027")
        # A month view of a year not yet running starts at its first month.
        self.assertEqual(context["period"], 10)

    def test_the_running_year_is_still_one_choice_away(self):
        context = self._context("2026-09-28 09:00:00", fy="2026")
        self.assertEqual(context["fy"], "2026")
        self.assertIn("2026", context["fy_options"])

    def test_before_the_next_year_opens_it_opens_on_the_running_year(self):
        self.assertEqual(self._context("2026-08-20 09:00:00")["fy"], "2026")

    def test_once_the_year_turns_it_opens_on_the_new_running_year(self):
        self.assertEqual(self._context("2026-10-05 09:00:00")["fy"], "2027")
