"""My Plan answers with the plan; Planned and remaining follows it.

Owner, 2026-10-13: "reduced the load, save and reschedule time further to 1
second or less", and of My Plan: "do 3 as well" (load the readiness panel
after the page). Read from production that evening, My Plan took a median of
4.5 seconds to answer. The person's own Planned and remaining reads every
school they hold to put six lines above the plan, and their training summary
sits under it; together they were about four statements in ten of the page.

The page now leaves a place for the two and asks for them once it has been
drawn. Held here: who is left a place and who is not, that the panel shows
what the page showed and its links are the page's, when the tables stay in
the page's own answer, and that the reads behind a rail the page stopped
drawing are no longer made.
"""

from __future__ import annotations

import re
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.planning import planning_monitor
from apps.planning.test_monitors_people import FY, PeopleFixture


def _text(response) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.content.decode()))


class ThePageLeavesAPlaceTest(PeopleFixture):
    def test_someone_who_plans_visits_is_left_a_place_and_no_table(self):
        self.client.force_login(self.cara_user)
        with mock.patch.object(
            planning_monitor, "own_monitor", wraps=planning_monitor.own_monitor
        ) as read:
            response = self.client.get(f"/my-plan?fy={FY}")
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn("data-my-plan-readiness-later", page)
        self.assertIn('hx-trigger="load"', page)
        self.assertNotIn("data-my-plan-queues", page)
        self.assertIsNone(response.context["readiness"])
        # Nothing of the person's schools was read for the page.
        read.assert_not_called()

    def test_the_place_asks_with_the_pages_own_query(self):
        self.client.force_login(self.cara_user)
        page = self.client.get(f"/my-plan?fy={FY}&quarter=Q1").content.decode()
        asked = re.search(r'hx-get="(/my-plan/readiness[^"]*)"', page).group(1)
        self.assertIn(f"fy={FY}", asked)
        self.assertIn("quarter=Q1", asked)

    def test_a_filter_reload_of_the_workspace_leaves_the_place_too(self):
        self.client.force_login(self.cara_user)
        response = self.client.get(f"/my-plan?fy={FY}", HTTP_HX_REQUEST="true")
        self.assertIn("data-my-plan-readiness-later", response.content.decode())

    def test_someone_who_plans_no_visits_is_left_nothing(self):
        self.client.force_login(self.cd_user)
        response = self.client.get(f"/my-plan?fy={FY}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("data-my-plan-readiness-later", response.content.decode())
        self.assertNotIn("/my-plan/readiness", response.content.decode())

    def test_the_page_takes_fewer_statements_than_the_page_and_its_tables(self):
        self.client.force_login(self.cara_user)
        self.client.get(f"/my-plan?fy={FY}")
        with CaptureQueriesContext(connection) as page:
            self.client.get(f"/my-plan?fy={FY}")
        # Asked for a list, the page answers with the tables as it used to.
        with CaptureQueriesContext(connection) as with_tables:
            self.client.get(f"/my-plan?fy={FY}&list=made_up")
        self.assertLess(len(page), len(with_tables) * 0.8)


class ThePanelTest(PeopleFixture):
    def test_it_shows_planned_and_remaining_and_the_training_summary(self):
        self.client.force_login(self.cara_user)
        response = self.client.get(f"/my-plan/readiness?fy={FY}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["readiness"].staff_visits.target, 560)
        self.assertIn("my_training_summary", response.context)
        page = _text(response)
        self.assertIn(f"Planned and remaining · FY {FY}", page)
        self.assertIn("Your visits", page)
        self.assertNotIn("data-my-plan-readiness-later", response.content.decode())

    def test_its_figures_open_their_list_on_the_page(self):
        """A figure's link is a query on the page the panel sits in, with
        whatever the page was already filtered by."""
        self.client.force_login(self.cara_user)
        body = self.client.get(f"/my-plan/readiness?fy={FY}").content.decode()
        links = re.findall(r'data-plan-count="[a-z_]+"', body)
        self.assertTrue(links)
        for href in re.findall(r'hx-get="([^"]+)"[^>]*data-plan-count=', body):
            self.assertTrue(href.startswith("?"), href)
            self.assertIn(f"fy={FY}", href)
            self.assertIn("list=", href)

    def test_it_is_the_year_the_page_shows_when_none_is_named(self):
        from datetime import date

        from apps.core.fy import get_operational_fy

        self.client.force_login(self.cara_user)
        page = self.client.get("/my-plan")
        panel = self.client.get("/my-plan/readiness")
        self.assertEqual(
            str(panel.context["fy"]), str(get_operational_fy(date.today()))
        )
        self.assertEqual(str(panel.context["fy"]), str(page.context["fy"]))

    def test_someone_who_plans_no_visits_gets_no_table(self):
        self.client.force_login(self.cd_user)
        response = self.client.get(f"/my-plan/readiness?fy={FY}")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["readiness"])
        self.assertNotIn("data-my-plan-queues", response.content.decode())

    def test_it_is_for_someone_signed_in(self):
        response = self.client.get(f"/my-plan/readiness?fy={FY}")
        self.assertNotEqual(response.status_code, 200)


class WhenTheTablesStayInTheAnswerTest(PeopleFixture):
    def test_the_schools_behind_a_figure_come_with_the_page(self):
        """The reader has just asked to be shown them: the page scrolls to
        the list, which has to be in the answer."""
        self.client.force_login(self.cara_user)
        response = self.client.get(f"/my-plan?fy={FY}&list=all")
        page = response.content.decode()
        self.assertIn('id="plan-list"', page)
        self.assertIn("data-my-plan-queues", page)
        self.assertNotIn("data-my-plan-readiness-later", page)

    def test_the_figures_as_data_are_the_figures(self):
        self.client.force_login(self.cara_user)
        payload = self.client.get(f"/my-plan?fy={FY}&format=readiness-json").json()
        self.assertEqual(payload["readiness"]["visits"]["staff"]["target"], 560)

    def test_an_export_reads_none_of_it(self):
        self.client.force_login(self.cara_user)
        with mock.patch.object(
            planning_monitor, "own_monitor", wraps=planning_monitor.own_monitor
        ) as read:
            response = self.client.get(f"/my-plan?fy={FY}&export=xlsx")
        self.assertEqual(response.status_code, 200)
        read.assert_not_called()


class TheRailThePageStoppedDrawingTest(PeopleFixture):
    def test_its_reads_are_made_only_when_something_reads_it(self):
        from apps.my_plan.services import get_frontend_context

        with CaptureQueriesContext(connection) as building:
            context = get_frontend_context(
                self.cara_user, {"fy": FY}, with_readiness=False
            )
        with CaptureQueriesContext(connection) as reading:
            today = list(context["upcoming_today"])
            attention = list(context["attention_needed"])
            step = context["next_recommended_action"]["title"]
        self.assertEqual((today, attention), ([], []))
        self.assertEqual(step, "You're on track!")
        # Today's work, the rescheduled and those missing a Salesforce ID:
        # three reads, made on the first of the three. Work awaiting evidence
        # was a fourth until the upload was switched off (UPLOAD-OFF, owner
        # 2026-10-13).
        self.assertEqual(len(reading), 3)
        self.assertFalse([q for q in building if '"reschedule_count" > 0' in q["sql"]])
