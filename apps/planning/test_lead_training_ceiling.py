"""A Programme Lead is on the training ceiling list (owner, 2026-10-06).

"On the training target ceiling created by the Leads. can you make sure they
are included on the list. That they can set their own ceiling and that of
their CCEOs."

A Lead holds schools and schedules trainings like the officers they
supervise, and the ceiling list was those officers alone: the Lead was not in
the drawer's staff list, could not be given a ceiling by anybody, and had no
column in the training summary, theirs or the country's.
"""

from __future__ import annotations

from django.db import transaction

from apps.core.exceptions import BadRequest, Forbidden
from apps.planning import training_ceilings, training_summary
from apps.planning.models import TrainingCeiling

from .test_training_ceilings import CeilingFixture


class TheLeadIsOnTheListTest(CeilingFixture):
    def test_the_lead_comes_first_then_their_officers_by_name(self):
        options = training_ceilings.ceiling_staff_options(self.pl)

        self.assertEqual(
            [p.user.name for p in options],
            ["Lead Lydia", "Mary Officer", "Standard CCEO"],
        )

    def test_nobody_else_s_officer_is_on_it(self):
        names = [p.user.name for p in training_ceilings.ceiling_staff_options(self.pl)]

        self.assertNotIn("Outside Officer", names)
        self.assertNotIn("Lead Lucas", names)

    def test_an_officer_has_no_list(self):
        self.assertEqual(training_ceilings.ceiling_staff_options(self.user), [])

    def test_the_drawer_offers_the_lead_their_own_name(self):
        response = self.client_for(self.pl).get(
            "/training-ceilings/set", HTTP_HX_REQUEST="true"
        )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(f'value="{self.pl_staff.id}"', body)
        self.assertIn("Lead Lydia (you)", body)
        self.assertIn("You, and the officers you supervise.", body)
        self.assertLess(body.index("Lead Lydia"), body.index("Mary Officer"))


class TheLeadSetsTheirOwnCeilingTest(CeilingFixture):
    def test_a_lead_sets_their_own(self):
        row = training_ceilings.set_ceiling(
            self.pl,
            staff_id=self.pl_staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
            ceiling="15",
        )

        self.assertEqual((row.staff_id, row.ceiling), (self.pl_staff.id, 15))
        self.assertEqual(row.set_by_role, "Program Lead")
        self.assertTrue(training_ceilings.may_set_ceiling(self.pl, self.pl_staff.id))

    def test_and_still_sets_their_officers(self):
        for staff in (self.staff, self.mary_staff):
            training_ceilings.set_ceiling(
                self.pl,
                staff_id=staff.id,
                training_id=self.leadership.id,
                fy=self.fy,
                ceiling="20",
            )

        self.assertEqual(TrainingCeiling.objects.count(), 2)

    def test_a_lead_does_not_set_another_lead_s(self):
        with self.assertRaises(Forbidden):
            training_ceilings.set_ceiling(
                self.pl,
                staff_id=self.other_pl_staff.id,
                training_id=self.leadership.id,
                fy=self.fy,
                ceiling="15",
            )
        self.assertFalse(
            training_ceilings.may_set_ceiling(self.pl, self.other_pl_staff.id)
        )

    def test_an_officer_does_not_set_their_own(self):
        with self.assertRaises(Forbidden):
            training_ceilings.set_ceiling(
                self.user,
                staff_id=self.staff.id,
                training_id=self.leadership.id,
                fy=self.fy,
                ceiling="15",
            )

    def test_the_lead_changes_and_removes_their_own(self):
        row = training_ceilings.set_ceiling(
            self.pl,
            staff_id=self.pl_staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
            ceiling="15",
        )
        training_ceilings.set_ceiling(
            self.pl,
            staff_id=self.pl_staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
            ceiling="18",
        )
        self.assertEqual(TrainingCeiling.objects.get(id=row.id).ceiling, 18)

        training_ceilings.remove_ceiling(self.pl, row.id)

        self.assertFalse(TrainingCeiling.objects.exists())

    def test_the_drawer_saves_the_lead_s_own_ceiling(self):
        response = self.client_for(self.pl).post(
            "/training-ceilings/set",
            {
                "staff_id": self.pl_staff.id,
                "training_id": self.leadership.id,
                "fy": self.fy,
                "ceiling": "12",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertLess(response.status_code, 400)
        row = TrainingCeiling.objects.get(staff_id=self.pl_staff.id)
        self.assertEqual(row.ceiling, 12)

    def test_the_lead_s_own_ceiling_is_held_like_anybody_s(self):
        """The ceiling is a rule on the server, the Lead's included."""
        training_ceilings.set_ceiling(
            self.pl,
            staff_id=self.pl_staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
            ceiling="2",
        )

        with transaction.atomic():
            training_ceilings.reserve(
                staff_id=self.pl_staff.id,
                course_id=self.leadership.id,
                fy=self.fy,
                requested=2,
            )
        with self.assertRaises(BadRequest), transaction.atomic():
            training_ceilings.reserve(
                staff_id=self.pl_staff.id,
                course_id=self.leadership.id,
                fy=self.fy,
                requested=3,
            )


class TheLeadHasAColumnTest(CeilingFixture):
    def setUp(self):
        super().setUp()
        self.ceiling(value=20)
        self.ceiling(staff=self.pl_staff, value=10)
        self.group(self.members[:6])

    def page(self, user, **query):
        return self.client_for(user).get(
            "/team-planning-oversight/", {"view": "trainings", "fy": self.fy, **query}
        )

    def test_the_lead_s_table_opens_with_their_own_column(self):
        summary = training_summary.for_reader(self.pl, self.fy)

        self.assertEqual(
            [(c["name"], c["is_lead"]) for c in summary.columns],
            [("Lead Lydia", True), ("Mary Officer", False), ("Standard CCEO", False)],
        )
        self.assertTrue(summary.may_set)

    def test_the_lead_s_cell_reads_the_ceiling_they_set_themselves(self):
        summary = training_summary.for_reader(self.pl, self.fy)
        row = next(r for r in summary.rows if r.training_id == self.leadership.id)
        cells = {cell.staff_id: cell for cell in row.cells}

        self.assertEqual(cells[self.pl_staff.id].limit, 10)
        self.assertEqual(cells[self.pl_staff.id].schools, 0)
        self.assertEqual(cells[self.staff.id].schools, 6)

    def test_the_page_marks_the_lead_s_column(self):
        body = self.page(self.pl).content.decode()

        self.assertIn("# Schools<br>(Lead Lydia · PL)", body)
        self.assertIn("# Schools<br>(Mary Officer)", body)

    def test_the_country_s_table_lists_the_leads_with_their_teams(self):
        director = self._person("lead-cd@edify.org", "Director Dan", "CountryDirector")[
            0
        ]

        summary = training_summary.for_reader(director, self.fy)
        names = [c["name"] for c in summary.columns]

        for name in ("Lead Lydia", "Lead Lucas", "Mary Officer", "Outside Officer"):
            self.assertIn(name, names)
        # Each Lead, then the officers who report to them: the columns read
        # as teams, the Leads by name.
        self.assertEqual(
            [n for n in names if n in ("Lead Lucas", "Outside Officer")],
            ["Lead Lucas", "Outside Officer"],
        )
        self.assertEqual(names.index("Outside Officer"), names.index("Lead Lucas") + 1)
        self.assertLess(names.index("Lead Lydia"), names.index("Mary Officer"))
        self.assertLess(names.index("Lead Lydia"), names.index("Standard CCEO"))
        self.assertLess(names.index("Lead Lucas"), names.index("Lead Lydia"))
        self.assertEqual(
            {c["name"] for c in summary.columns if c["is_lead"]},
            {"Lead Lydia", "Lead Lucas"},
        )
        self.assertFalse(summary.may_set)

    def test_one_lead_s_team_is_the_lead_and_their_officers(self):
        director = self._person("lead-cd2@edify.org", "Director Di", "CountryDirector")[
            0
        ]

        summary = training_summary.for_reader(director, self.fy, lead=self.pl_staff.id)

        self.assertEqual(
            [c["name"] for c in summary.columns],
            ["Lead Lydia", "Mary Officer", "Standard CCEO"],
        )

    def test_a_lead_with_no_officer_yet_is_still_a_lead_to_choose(self):
        self._person("lead-new@edify.org", "Lead Nora", "Program Lead")
        director = self._person("lead-cd3@edify.org", "Director Do", "CountryDirector")[
            0
        ]

        summary = training_summary.for_reader(director, self.fy)

        self.assertIn("Lead Nora", [name for _id, name in summary.leads])
        self.assertIn("Lead Nora", [c["name"] for c in summary.columns])
