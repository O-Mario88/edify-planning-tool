"""A school on a drill-down list can be acted on (owner, 2026-10-05).

"the list should have the action buttons with schedule or assign for school
that need to be scheduled or assigned ... and for schools that need
rescheduling should be in the action button. double schedule (staff and
partner) list should have option for the staff to cancel and other actions
needed and ensure group actions can be applied to those schools and tables
and lists as well."

What is pinned here: what a listed school offers its holder, that a
supervisor is offered nothing on a colleague's school, and that the list on
My Plan draws the menu, the tick box and the bar's Assign.
"""

from __future__ import annotations

from django.conf import settings
from django.test import SimpleTestCase

from apps.activities.test_profile_activities import PASSWORD, ProfileActivitiesFixture
from apps.planning import list_actions
from apps.planning.planning_monitor import list_schools, own_monitor

TEMPLATES = settings.BASE_DIR / "templates"


class WhatAListedSchoolOffers(ProfileActivitiesFixture):
    def _rows(self, key="all"):
        officer = own_monitor(self.cceo, self.fy)
        return {row.id: row for row in list_schools([officer], key)}

    def test_the_holder_is_offered_the_planning_pages_own_actions(self):
        rows = self._rows()

        tickable = list_actions.offer(rows.values(), self.cceo, self.fy)

        self.assertTrue(tickable)
        acts = rows[self.school.id].acts
        self.assertTrue(acts.mine)
        # Schedule and Assign: offered, or greyed with the gate's reason.
        self.assertTrue(acts.schedule_url or acts.schedule_reason)
        self.assertTrue(acts.assign_url or acts.assign_reason)
        if acts.schedule_url:
            self.assertIn(f"school_id={self.school.school_id}", acts.schedule_url)

    def test_staff_work_already_planned_there_can_be_moved_or_called_off(self):
        rows = self._rows()
        list_actions.offer(rows.values(), self.cceo, self.fy)

        acts = rows[self.school.id].acts
        planned = {activity_id for activity_id, _label, _day in acts.activities}
        self.assertIn(self.planned.id, planned)
        # Finished and cancelled work is not offered again.
        self.assertNotIn(self.verified.id, planned)
        self.assertNotIn(self.cancelled.id, planned)
        self.assertTrue(acts.reschedule_url and acts.cancel_url)
        self.assertTrue(acts.can_tick)
        self.assertIn(self.planned.id, acts.activity_ids)

    def test_one_planned_activity_opens_its_own_drawers(self):
        self.overdue.status = "cancelled"
        self.overdue.save(update_fields=["status"])
        rows = self._rows()
        list_actions.offer(rows.values(), self.cceo, self.fy)

        acts = rows[self.school.id].acts
        if len(acts.activities) == 1:
            only = acts.activities[0][0]
            self.assertEqual(acts.reschedule_url, f"/my-plan/{only}/reschedule-drawer")
            self.assertEqual(acts.cancel_url, f"/my-plan/{only}/cancel-drawer")
        else:
            self.assertIn("/activity-selection/reschedule?ids=", acts.reschedule_url)

    def test_a_supervisor_is_offered_nothing_on_a_colleagues_school(self):
        """§1B: a Programme Lead reads a CCEO's schools and does not run them."""
        rows = self._rows()

        tickable = list_actions.offer(rows.values(), self.pl, self.fy)

        self.assertFalse(tickable)
        for row in rows.values():
            self.assertFalse(row.acts.mine)
            self.assertFalse(row.acts.any)


class TheListOnMyPlan(ProfileActivitiesFixture):
    def test_it_draws_the_menu_the_tick_box_and_the_bars_assign(self):
        self.client.login(email=self.cceo.email, password=PASSWORD)

        response = self.client.get("/my-plan", {"period": "fy", "list": "all"})

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        listed = html[html.index("data-plan-list") :]
        self.assertIn("data-school-pick", listed)
        self.assertIn('data-select-all="input[data-school-pick]"', listed)
        self.assertIn("Open school", listed)
        self.assertIn("data-needs-schools", html)
        self.assertIn('hx-get="/planning/bulk-assign-partner-drawer"', html)


class TheListContract(SimpleTestCase):
    def test_both_lists_draw_the_same_row_actions_and_tick_cell(self):
        for name in (
            "partials/my_plan/readiness_list.html",
            "partials/oversight/monitor_workspace.html",
        ):
            with self.subTest(template=name):
                text = (TEMPLATES / name).read_text()
                self.assertIn("school_list_actions", text)
                self.assertIn("partials/planning/_list_row_actions.html", text)
                self.assertIn("partials/planning/_list_pick_cell.html", text)

    def test_the_script_reads_a_ticked_schools_activities(self):
        script = (settings.BASE_DIR / "static/js/group-select.js").read_text()
        self.assertIn("data-school-pick", script)
        self.assertIn("data-activity-ids", script)
        self.assertIn("school_ids", script)
