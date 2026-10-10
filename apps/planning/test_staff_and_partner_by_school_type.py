"""Planned and remaining flags visits planned on both sides, by school type.

Owner, 2026-10-07: "On this table Planned and remaining · FY 2027, can you
separates Staff and Partner columns for core and clients ... the idea is to
flag visits planned by both staff and also assigned to partners for visits
... core one should have 2 visits from staff and 2 from partner. more than
those should be flagged."

The one "Staff and Partner" column counted every school staff scheduled a
visit at that is also in a Partner's hands, Core schools included, where that
is the package itself. It is now two columns, each opening its schools:

* Client: Staff and Partner — a Client, Core Trained or Core Graduate school
  takes one visit, so one on both sides is booked twice;
* Core: over 2 Staff or 2 Partner visits — a Core school is flagged only with
  more than the two visits by staff and two by a Partner it takes.
"""

import re

from django.test import SimpleTestCase

from apps.partners.models import Partner
from apps.planning import readiness
from apps.planning.planning_monitor import in_list
from apps.planning.test_monitors_people import FY, PeopleFixture
from apps.planning.test_planning_readiness import officer, school


class TwoFlagsTests(SimpleTestCase):
    def setUp(self):
        self.person = officer(
            [
                # Core: the package, and nothing past it.
                school(1, "core", staff_visits=2, partner_visits=2),
                school(2, "core", staff_visits=2, partner_visits=1, partner_pending=1),
                # Core: past it, by staff, by a Partner, and by a Partner's
                # visit that is still awaiting its date.
                school(3, "core", staff_visits=3),
                school(4, "core", partner_visits=3),
                school(5, "core", partner_visits=2, partner_visits_undated=1),
                # Client: on both sides.
                school(6, staff_visits=1, partner_pending=1),
                school(7, "core_trained", staff_visits=1, partner_visits=1),
                # Client: on one side only.
                school(8, "core_graduate", staff_visits=3),
                school(9, partner_visits=1),
            ],
            planned_core=7,
            planned_client=5,
        )
        self.figures = readiness.person_readiness(self.person)

    def listed(self, key):
        return [s.id for s in self.person.schools if in_list(s, key)]

    def test_a_core_school_is_flagged_past_two_and_two(self):
        self.assertEqual(self.figures.core_visits_over, 3)
        self.assertEqual(self.listed("core_visits_over"), ["s3", "s4", "s5"])

    def test_staff_and_a_partner_both_at_a_core_school_is_its_package(self):
        for code in ("s1", "s2"):
            self.assertNotIn(code, self.listed("core_visits_over"))

    def test_a_client_school_on_both_sides_is_flagged(self):
        self.assertEqual(self.figures.client_staff_and_partner, 2)
        self.assertEqual(self.listed("client_staff_and_partner"), ["s6", "s7"])
        for one in self.person.schools:
            if in_list(one, "client_staff_and_partner"):
                self.assertTrue(readiness.is_duplicate(one), one.id)

    def test_each_flag_keeps_to_its_own_kind_of_school(self):
        for one in self.person.schools:
            if one.is_core:
                self.assertFalse(in_list(one, "client_staff_and_partner"), one.id)
            else:
                self.assertFalse(in_list(one, "core_visits_over"), one.id)

    def test_a_team_adds_its_people_up(self):
        other = readiness.person_readiness(
            officer(
                [
                    school(20, staff_visits=1, partner_visits=1),
                    school(21, "core", staff_visits=4),
                ],
                planned_core=4,
                planned_client=1,
            )
        )
        team = readiness.total([self.figures, other])
        self.assertEqual((team.core_visits_over, team.client_staff_and_partner), (4, 3))
        self.assertEqual(readiness.problems(team), [])

    def test_the_two_are_served_as_data(self):
        visits = self.figures.as_dict()["visits"]
        self.assertEqual(visits["core_schools_past_two_staff_or_two_partner_visits"], 3)
        self.assertEqual(
            visits["client_schools_scheduled_by_staff_and_with_partner"], 2
        )


class OnThePagesTests(PeopleFixture):
    """Cara holds one Core and one Client school."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.partner = Partner.objects.create(name="Both Org", region_name="R")

    def partner_visit(self, held, **more):
        return self._work(
            self.cara,
            "school_visit",
            school=held,
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            **{"status": "partner_scheduled", "partner_date_set_by": "partner", **more},
        )

    def monitor(self, extra=""):
        self.client.force_login(self.cd_user)
        response = self.client.get(f"/planning-monitor/?view=readiness&fy={FY}{extra}")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def count(self, page, key):
        found = re.search(rf'data-monitor-count="{key}">(\d+)<', page)
        return int(found.group(1)) if found else 0

    def test_the_monitor_has_a_column_for_each(self):
        page = self.monitor()
        core = page.find("Core: over 2 Staff or 2 Partner visits</th>")
        client = page.find("Client: Staff and Partner</th>")
        self.assertTrue(0 < core < client, (core, client))
        self.assertNotIn(">Staff and Partner</th>", page)
        # A group's heading row spans every column of the table.
        head = page[page.rfind("<thead>", 0, core) : page.find("</thead>", core)]
        self.assertIn(f'<th colspan="{head.count("<th ")}" scope="colgroup">', page)

    def test_the_core_package_itself_is_not_flagged(self):
        for _ in range(2):
            self._work(self.cara, "school_visit", school=self.core)
            self.partner_visit(self.core)
        page = self.monitor()
        self.assertEqual(self.count(page, "core_visits_over"), 0)
        self.assertEqual(self.count(page, "client_staff_and_partner"), 0)

    def test_a_third_staff_visit_at_a_core_school_is_flagged(self):
        for _ in range(3):
            self._work(self.cara, "school_visit", school=self.core)
        page = self.monitor()
        self.assertRegex(
            page, r'data-edify-tone="danger" data-monitor-count="core_visits_over">1<'
        )
        listed = self.monitor("&gap=core_visits_over")
        listed = listed[listed.find('data-monitor-list="core_visits_over"') :]
        self.assertIn("PPL-C", listed)
        self.assertNotIn(">PPL-1<", listed)

    def test_a_third_partner_visit_counts_before_the_partner_dates_it(self):
        for _ in range(2):
            self.partner_visit(self.core)
        self.assertEqual(self.count(self.monitor(), "core_visits_over"), 0)
        self.partner_visit(
            self.core,
            status="assigned_to_partner",
            planned_date=None,
            partner_date_set_by="",
        )
        self.assertEqual(self.count(self.monitor(), "core_visits_over"), 1)

    def test_a_client_school_on_both_sides_is_flagged(self):
        self._work(self.cara, "school_visit")
        self.partner_visit(self.client_school)
        page = self.monitor()
        self.assertRegex(
            page,
            r'data-edify-tone="danger" data-monitor-count="client_staff_and_partner">1<',
        )
        listed = self.monitor("&gap=client_staff_and_partner")
        listed = listed[listed.find('data-monitor-list="client_staff_and_partner"') :]
        self.assertIn("PPL-1", listed)
        self.assertNotIn(">PPL-C<", listed)

    def test_my_plan_says_the_two_flags(self):
        for _ in range(3):
            self._work(self.cara, "school_visit", school=self.core)
        self._work(self.cara, "school_visit")
        self.partner_visit(self.client_school)
        self.client.force_login(self.cara_user)
        response = self.client.get(f"/my-plan?fy={FY}")
        self.assertEqual(response.status_code, 200)
        figures = response.context["readiness"]
        self.assertEqual(
            (figures.core_visits_over, figures.client_staff_and_partner), (1, 1)
        )
        page = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.content.decode()))
        self.assertIn("1 Client school you scheduled is also with a Partner", page)
        self.assertIn("1 Core school has more than the two staff visits", page)

    def test_my_plan_says_nothing_when_there_is_nothing_to_flag(self):
        self._work(self.cara, "school_visit", school=self.core)
        self.partner_visit(self.core)
        self.client.force_login(self.cara_user)
        page = self.client.get(f"/my-plan?fy={FY}").content.decode()
        self.assertNotIn("data-both-client", page)
        self.assertNotIn("data-core-over", page)
