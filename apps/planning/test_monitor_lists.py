"""Every count opens the schools behind it (owner, 2026-10-05).

"On the activity summaries, add links to the actual table on every number on
the tables above and on the country oversight tables ... All those numbers
should be link to the actual tables where those schools are located."

What is pinned here: which schools each list holds, that a list is not a gap
(no follow-up is sent from it), that every key a template links to is a list
the monitor knows, and that My Plan's own figures open the planner's own
schools.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.test import SimpleTestCase

from apps.activities.test_profile_activities import PASSWORD, ProfileActivitiesFixture
from apps.planning import planning_monitor as pm

TEMPLATES = settings.BASE_DIR / "templates"


def _school(**fields) -> pm.SchoolState:
    base = dict(
        id="s1",
        code="S-1",
        name="A School",
        school_type="client",
        district="D",
        cluster_id="c1",
        cluster_name="C",
        clustered=True,
        officer_id="o1",
        officer_name="Officer",
        lead_id="l1",
        lead_name="Lead",
    )
    base.update(fields)
    return pm.SchoolState(**base)


class WhichSchoolsAListHolds(SimpleTestCase):
    def test_a_client_school_with_nothing_planned(self):
        school = _school()
        for key in (
            "all",
            "client",
            "staff_queue",
            "staff_visits_left",
            "client_staff_visits_left",
            "training_due",
            "partner_queue",
            "partner_left",
            "partner_visits_left",
            "not_in_project",
            "not_yet_planned",
        ):
            self.assertTrue(pm.in_list(school, key), key)
        for key in (
            "core",
            "visited",
            "with_partner",
            "training",
            "in_project",
            "fully_planned",
            "duplicates",
            "core_staff_visits_left",
        ):
            self.assertFalse(pm.in_list(school, key), key)

    def test_a_client_school_visited_and_trained_is_fully_planned(self):
        school = _school(staff_visits=1, group_training=True, in_project=True)

        for key in ("visited", "client_staff_visits", "training", "fully_planned"):
            self.assertTrue(pm.in_list(school, key), key)
        self.assertTrue(pm.in_list(school, "in_project"))
        self.assertFalse(pm.in_list(school, "staff_visits_left"))
        self.assertFalse(pm.in_list(school, "not_yet_planned"))

    def test_a_school_in_a_partners_hands(self):
        waiting = _school(partner_pending=1)
        dated = _school(partner_visits=1)

        self.assertTrue(pm.in_list(waiting, "with_partner"))
        self.assertTrue(pm.in_list(waiting, "partner_waiting"))
        self.assertFalse(pm.in_list(waiting, "partner_dated"))
        self.assertTrue(pm.in_list(dated, "partner_dated"))
        # The Partner's school is not owed a staff visit.
        self.assertFalse(pm.in_list(waiting, "staff_visits_left"))
        self.assertFalse(pm.in_list(waiting, "staff_queue"))

    def test_a_core_school_is_measured_two_and_two(self):
        core = _school(school_type="core", staff_visits=1, core_partner_visits=2)

        self.assertTrue(pm.in_list(core, "core"))
        self.assertTrue(pm.in_list(core, "core_staff_visits"))
        self.assertTrue(pm.in_list(core, "core_staff_visits_left"))
        self.assertFalse(pm.in_list(core, "core_partner_visits_left"))
        self.assertTrue(pm.in_list(core, "core_partner_trainings_left"))
        self.assertTrue(pm.in_list(core, "core_no_partner_half"))
        self.assertTrue(pm.in_list(core, "partly_planned"))

    def test_a_gap_is_still_read_by_the_school_itself(self):
        school = _school(clustered=False)

        self.assertTrue(pm.in_list(school, "not_clustered"))
        self.assertTrue(pm.in_list(school, "no_visit"))

    def test_lists_read_the_outreach_schools_and_gaps_do_not(self):
        held = _school(id="a", name="Held")
        champion = _school(id="b", name="Champion", school_type="champion")
        officer = pm.OfficerMonitor(
            key="o1",
            name="Officer",
            lead_id="l1",
            lead_name="Lead",
            schools=[held],
            outreach_schools=[champion],
        )

        self.assertEqual([s.id for s in pm.list_schools([officer], "all")], ["b", "a"])
        self.assertEqual([s.id for s in pm.list_schools([officer], "no_visit")], ["a"])
        self.assertEqual(
            [s.id for s in pm.list_schools([officer], "all", school_type="champion")],
            ["b"],
        )

    def test_a_row_says_whose_schools_its_counts_open(self):
        officer = pm.OfficerMonitor(key="o1", name="O", lead_id="l1", lead_name="L")
        team = pm.LeadMonitor(key="l1", name="L", officers=[officer])
        everyone = pm.LeadMonitor(key="all", name="All", officers=[officer])

        self.assertEqual(officer.list_scope, "&officer=o1")
        self.assertEqual(team.list_scope, "&program_lead=l1")
        self.assertEqual(everyone.list_scope, "")


class ListsAreNotGaps(SimpleTestCase):
    def test_a_list_has_a_label_and_is_not_offered_as_a_gap(self):
        gaps = dict(pm.GAPS)
        for key, label in pm.LISTS:
            self.assertTrue(label)
            self.assertNotIn(key, gaps)
            self.assertEqual(pm.GAP_LABELS[key], label)

    def test_follow_ups_are_sent_from_gaps_only(self):
        view = (
            settings.BASE_DIR / "apps/frontend/views/oversight_views.py"
        ).read_text()
        self.assertIn('"monitor_can_send": gap in dict(GAPS)', view)


class EveryLinkedKeyIsKnown(SimpleTestCase):
    """A count that links to a list the monitor does not know opens nothing."""

    KEYED = re.compile(r'\b(?:key|planned_key|target_key|left_key|list)="([a-z_]+)"')

    def _keys(self, name: str) -> set[str]:
        return set(self.KEYED.findall((TEMPLATES / name).read_text()))

    def test_the_monitor_tables(self):
        for name in (
            "partials/oversight/_monitor_row.html",
            "partials/oversight/_readiness_row.html",
            "partials/oversight/_monitor_inventory.html",
            "partials/my_plan/readiness.html",
            "partials/country_oversight/_cells.html",
            "partials/country_oversight/_types.html",
        ):
            with self.subTest(template=name):
                keys = self._keys(name)
                self.assertTrue(keys)
                self.assertEqual(keys - set(pm.GAP_LABELS), set())

    def test_the_counts_are_drawn_through_the_linking_partials(self):
        for name, partial in (
            ("partials/oversight/_monitor_row.html", "_monitor_count.html"),
            ("partials/oversight/_readiness_cell.html", "_monitor_count.html"),
            ("partials/oversight/_monitor_inventory.html", "_monitor_count.html"),
            ("partials/my_plan/_readiness_row.html", "_readiness_count.html"),
            ("partials/country_oversight/_cells.html", "_figure_link.html"),
            ("partials/country_oversight/_types.html", "_figure_link.html"),
        ):
            with self.subTest(template=name):
                self.assertIn(partial, (TEMPLATES / name).read_text())

    def test_the_list_has_somewhere_to_land(self):
        workspace = (
            TEMPLATES / "partials/oversight/monitor_workspace.html"
        ).read_text()
        self.assertIn('id="monitor-list"', workspace)
        self.assertIn(
            'id="plan-list"',
            (TEMPLATES / "partials/my_plan/readiness_list.html").read_text(),
        )


class MyPlanFiguresOpenTheirSchools(ProfileActivitiesFixture):
    def setUp(self):
        super().setUp()
        self.client.login(email=self.cceo.email, password=PASSWORD)

    def test_a_figure_opens_the_planners_own_schools(self):
        response = self.client.get("/my-plan", {"period": "fy", "list": "all"})

        self.assertEqual(response.status_code, 200)
        listed = response.context["plan_list"]
        self.assertEqual(listed["key"], "all")
        self.assertEqual(
            {school.id for school in listed["schools"]},
            {self.school.id, self.other.id},
        )
        self.assertContains(response, 'data-plan-list="all"')
        self.assertContains(response, 'data-plan-count="staff_scheduled"')

    def test_no_list_is_drawn_unless_one_is_asked_for(self):
        response = self.client.get("/my-plan", {"period": "fy"})

        self.assertIsNone(response.context["plan_list"])
        self.assertNotContains(response, "data-plan-list")

    def test_an_unknown_list_opens_nothing(self):
        response = self.client.get("/my-plan", {"period": "fy", "list": "made_up"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["plan_list"])
