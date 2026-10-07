"""Planned and remaining (apps.planning.readiness).

Owner, 2026-10-07: a Programme Lead reads against 280 visits and a CCEO
against 560 whatever they hold ("target visits set for PL/CCEO and once they
have planned to that target, the rest they are supposed to assign to the
partners"), and somebody whose schools cannot take that many is told to
recruit more. That reverses 2026-10-03, when a small portfolio was measured
against what it held. These pin the arithmetic on the monitor's own row
shapes, with no database: a full plan reads 100% in every part, the Partner's
share is the schools beyond the staff target, and the figures add up before a
page shows them.
"""

from django.test import SimpleTestCase, override_settings

from apps.planning import readiness
from apps.planning.monitor_roster import ROLE_CCEO, ROLE_PL
from apps.planning.planning_monitor import LeadMonitor, OfficerMonitor, SchoolState


def school(n, school_type="client", **state) -> SchoolState:
    made = SchoolState(
        id=f"s{n}",
        code=f"UG{n:04d}",
        name=f"School {n}",
        school_type=school_type,
        district="",
        cluster_id="",
        cluster_name="",
        clustered=False,
        officer_id="o",
        officer_name="Officer",
        lead_id="l",
        lead_name="Lead",
    )
    for key, value in state.items():
        setattr(made, key, value)
    return made


def core_done(n) -> SchoolState:
    return school(
        n,
        "core",
        staff_visits=2,
        partner_visits=2,
        core_partner_visits=2,
        core_partner_trainings=2,
        core_staff_trainings=2,
        group_training=True,
        in_project=True,
    )


def officer(schools, *, role=ROLE_CCEO, planned_core=0, planned_client=0, outreach=()):
    return OfficerMonitor(
        key="o",
        name="Officer",
        lead_id="l",
        lead_name="Lead",
        visits_target=560 if role == ROLE_CCEO else 280,
        role=role,
        schools=list(schools),
        outreach_schools=list(outreach),
        planned_core=planned_core,
        planned_client=planned_client,
    )


class FullPlanReadsOneHundredTests(SimpleTestCase):
    def test_a_full_plan_is_100_in_every_part(self):
        """10 Core and 540 Client schools are a CCEO's 560 visits."""
        schools = [core_done(n) for n in range(10)] + [
            school(100 + n, staff_visits=1, group_training=True, in_project=True)
            for n in range(540)
        ]
        figures = readiness.person_readiness(
            officer(schools, planned_core=20, planned_client=540)
        )
        self.assertEqual(figures.staff_visits.target, 560)
        self.assertEqual(figures.staff_visits.remaining, 0)
        self.assertEqual(figures.partner_visits.target, 20)
        self.assertEqual(figures.partner_assignment.target, 10)
        self.assertEqual(
            [pillar["line"].percent for pillar in figures.pillars], [100] * 4
        )
        self.assertEqual(figures.score, 100)
        self.assertEqual(figures.net_visits_remaining, 0)
        self.assertEqual(figures.schools_to_recruit, 0)
        self.assertEqual(readiness.problems(figures), [])

    def test_a_small_portfolio_reads_against_560_and_is_told_to_recruit(self):
        """10 Core and 30 Client schools take 50 of a CCEO's 560 visits
        (owner, 2026-10-07: always 280 / 560, "but those with less should be
        notified to recruit more schools to meet the target")."""
        schools = [core_done(n) for n in range(10)] + [
            school(100 + n, staff_visits=1, group_training=True, in_project=True)
            for n in range(30)
        ]
        figures = readiness.person_readiness(
            officer(schools, planned_core=20, planned_client=30)
        )
        self.assertEqual(figures.staff_visits.target, 560)
        self.assertEqual(figures.staff_visits.planned, 50)
        self.assertEqual(figures.staff_visits.remaining, 510)
        self.assertEqual(figures.staff_visits.percent, 8)
        self.assertEqual(figures.portfolio_visits, 50)
        self.assertEqual(figures.schools_to_recruit, 510)
        self.assertEqual(figures.short_people, 1)
        # Nothing is beyond the target, so the Partner's is the Core half.
        self.assertEqual(figures.partner_visits.target, 20)
        self.assertEqual(figures.partner_assignment.target, 10)
        self.assertEqual(figures.score, (8 + 100 + 100 + 100) // 4)
        self.assertEqual(readiness.problems(figures), [])

    def test_a_champion_school_is_held_and_asks_no_visit_or_training(self):
        champion = school(900, "champion")
        figures = readiness.person_readiness(
            officer([core_done(1)], planned_core=2, outreach=[champion])
        )
        self.assertEqual(figures.schools_total, 2)
        self.assertEqual(figures.inventory["champion"].fully, 1)
        # The role's 560; the one Core school takes two of them.
        self.assertEqual(figures.staff_visits.target, 560)
        self.assertEqual(figures.schools_to_recruit, 558)
        # Held, and counted among the schools read for projects: one of the
        # two is in a project.
        self.assertEqual((figures.project_assigned, figures.project_total), (1, 2))
        # The project line is the person's ceilings (owner, 2026-10-06), and
        # nobody set this person one: it asks nothing.
        self.assertFalse(figures.project_assignment.required)
        self.assertEqual(figures.score, (0 + 100 + 100 + 100) // 4)

    def test_the_project_line_is_schools_added_of_the_ceilings_set(self):
        person = officer([core_done(1)], planned_core=2)
        person.project_ceiling, person.project_added = 4, 2
        figures = readiness.person_readiness(person)

        line = figures.project_assignment
        self.assertEqual((line.planned, line.target, line.remaining), (2, 4, 2))
        self.assertEqual(figures.score, (0 + 100 + 100 + 50) // 4)

    def test_somebody_holding_no_school_has_no_score(self):
        figures = readiness.person_readiness(officer([]))
        self.assertFalse(figures.applicable)
        self.assertIsNone(figures.as_dict()["completion"]["overall"])
        # Their target stands all the same, and every school of it is to
        # recruit.
        self.assertEqual(figures.staff_visits.target, 560)
        self.assertEqual(figures.schools_to_recruit, 560)


class CeilingAndPartnerShareTests(SimpleTestCase):
    def test_schools_beyond_a_leads_280_are_the_partners(self):
        """20 Core (40 visits) leave 240; 300 Client schools leave 60 over."""
        schools = [school(n, "core") for n in range(20)] + [
            school(100 + n) for n in range(300)
        ]
        figures = readiness.person_readiness(officer(schools, role=ROLE_PL))
        self.assertEqual(figures.staff_visits.target, 280)
        self.assertEqual(figures.partner_beyond_staff, 60)
        self.assertEqual(figures.partner_visits.target, 40 + 60)
        self.assertEqual(figures.partner_assignment.target, 20 + 60)
        # Training is counted by school: every school held takes one. The
        # Partner's training line is its half of the Core packages.
        self.assertEqual(figures.staff_trainings.target, 320)
        self.assertEqual(figures.partner_trainings.target, 40)

    def test_a_school_handed_over_inside_the_target_is_not_the_partners_target(self):
        """Nothing is beyond the 560, and 5 of 20 schools were handed over:
        staff's target is still 560, the Partner is asked nothing here, and
        what it holds is shown as held, past a target of none."""
        schools = [school(n, staff_visits=1) for n in range(15)] + [
            school(50 + n, partner_pending=1) for n in range(3)
        ]
        schools += [school(60 + n, partner_visits=1) for n in range(2)]
        figures = readiness.person_readiness(officer(schools, planned_client=15))
        self.assertEqual(figures.staff_visits.target, 560)
        self.assertEqual(figures.staff_visits.percent, 2)
        self.assertEqual(figures.partner_beyond_staff, 0)
        self.assertEqual(figures.partner_visits.target, 0)
        self.assertEqual(figures.partner_visits.planned, 2)
        self.assertEqual(figures.partner_visits.over, 2)
        self.assertEqual(figures.partner_visits_awaiting, 3)
        self.assertFalse(figures.partner_assignment.required)
        self.assertEqual(figures.partner_assignment.planned, 5)
        self.assertEqual(readiness.problems(figures), [])

    def test_past_the_ceiling_is_shown_and_never_counts_twice(self):
        schools = [school(n, staff_visits=1) for n in range(10)]
        figures = readiness.person_readiness(officer(schools, planned_client=564))
        self.assertEqual(figures.staff_visits.planned, 564)
        self.assertEqual(figures.staff_visits.over, 4)
        self.assertEqual(figures.staff_visits.percent, 100)

    def test_one_persons_extra_does_not_close_a_colleagues_gap(self):
        ahead = officer([school(n) for n in range(10)], planned_client=570)
        behind = officer([school(20 + n) for n in range(10)], planned_client=2)
        team = readiness.total(
            readiness.person_readiness(person) for person in (ahead, behind)
        )
        self.assertEqual(team.staff_visits.target, 1120)
        self.assertEqual(team.staff_visits.planned, 572)
        self.assertEqual(team.staff_visits.remaining, 558)
        self.assertEqual(team.staff_visits.percent, 50)
        # Each is 550 schools short of their own 560.
        self.assertEqual((team.schools_to_recruit, team.short_people), (1100, 2))

    def test_279_of_280_is_not_100(self):
        self.assertEqual(readiness.Line(280, 279, 279).percent, 99)


class TooFewSchoolsTests(SimpleTestCase):
    """Owner, 2026-10-07: "those with less should be notified to recruit
    more schools to meet the target"."""

    def short(self, core, client, role=ROLE_CCEO):
        schools = [school(n, "core") for n in range(core)] + [
            school(1000 + n) for n in range(client)
        ]
        return readiness.person_readiness(officer(schools, role=role))

    def test_a_core_school_takes_two_of_the_target_and_the_others_one(self):
        self.assertEqual(self.short(10, 30).schools_to_recruit, 560 - 50)
        self.assertEqual(self.short(0, 100, ROLE_PL).schools_to_recruit, 180)

    def test_enough_schools_is_none_to_recruit(self):
        for core, client in ((0, 560), (10, 540), (280, 0), (300, 0), (50, 900)):
            with self.subTest(core=core, client=client):
                figures = self.short(core, client)
                self.assertEqual(figures.schools_to_recruit, 0)
                self.assertEqual(figures.short_people, 0)

    def test_a_row_with_no_target_recruits_nothing(self):
        nobody = officer([school(1), school(2)])
        nobody.visits_target = 0
        figures = readiness.person_readiness(nobody)
        self.assertEqual(figures.staff_visits.target, 0)
        self.assertEqual(figures.schools_to_recruit, 0)

    def test_core_and_client_targets_add_up_to_the_role_target(self):
        for core, client in ((0, 0), (10, 30), (102, 556), (140, 5), (800, 0)):
            with self.subTest(core=core, client=client):
                person = officer(
                    [school(n, "core") for n in range(core)]
                    + [school(1000 + n) for n in range(client)]
                )
                figures = readiness.person_readiness(person)
                self.assertEqual(
                    person.core_visit_target + person.client_visit_target, 560
                )
                self.assertEqual(figures.staff_visits.target, 560)
                # What the Partner should hold is the same on both tabs.
                self.assertEqual(person.partner_needed, figures.partner_beyond_staff)
                self.assertEqual(
                    person.partner_visit_target, figures.partner_visits.target
                )
                self.assertEqual(person.schools_to_recruit, figures.schools_to_recruit)

    def test_the_figure_is_served_as_data(self):
        visits = self.short(10, 30).as_dict()["visits"]
        self.assertEqual(visits["schools_held_can_take"], 50)
        self.assertEqual(visits["schools_to_recruit"], 510)


class SchoolsAddUpTests(SimpleTestCase):
    def test_every_school_is_in_exactly_one_state(self):
        schools = [
            core_done(1),
            school(2, "core", staff_visits=1),
            school(3, "core"),
            school(4, staff_visits=1, in_school_training=True),
            school(5, "core_trained", partner_pending=1),
            school(6, "core_graduate"),
        ]
        figures = readiness.person_readiness(
            officer(schools, outreach=[school(7, "champion")])
        )
        self.assertEqual(
            (figures.schools_fully, figures.schools_partly, figures.schools_not_yet),
            (3, 2, 2),
        )
        self.assertEqual(figures.schools_total, 7)
        self.assertTrue(all(row.balanced for row in figures.types))
        self.assertEqual(
            [row.key for row in figures.types],
            ["core", "client", "core_trained", "core_graduate", "champion"],
        )

    def test_what_impact_assessment_looks_into(self):
        schools = [
            school(1, staff_visits=2),
            school(2, staff_visits=1, partner_pending=1),
            school(3, "core", core_partner_visits=2, core_partner_trainings=1),
            core_done(4),
        ]
        figures = readiness.person_readiness(officer(schools, planned_client=561))
        self.assertEqual(figures.duplicates, 2)
        self.assertEqual(figures.core_missing_partner_half, 1)
        self.assertEqual(figures.over_ceiling_people, 1)
        self.assertEqual(figures.over_ceiling_visits, 1)

    def test_a_dropped_school_is_named(self):
        figures = readiness.person_readiness(officer([school(1), school(2)]))
        found = readiness.problems(figures, expected_schools=3)
        self.assertEqual(len(found), 1)
        self.assertIn("3 operating schools in scope, 2 on the rows", found[0])

    @override_settings(DEBUG=True)
    def test_a_mismatch_fails_loudly_in_development(self):
        figures = readiness.person_readiness(officer([school(1)]))
        with self.assertRaises(readiness.ReadinessMismatch):
            readiness.verify(figures, where="test", expected_schools=2)

    @override_settings(DEBUG=False)
    def test_a_mismatch_is_logged_as_an_error_in_production(self):
        figures = readiness.person_readiness(officer([school(1)]))
        with self.assertLogs("apps.planning.readiness", level="ERROR"):
            readiness.verify(figures, where="test", expected_schools=2)

    def test_the_monitor_gets_figures_on_every_row(self):
        people = [officer([school(1, staff_visits=1)], planned_client=1)]
        totals = LeadMonitor(key="all", name="All", officers=people)
        lead = LeadMonitor(key="l", name="Lead", officers=people)
        figures = readiness.for_monitor(
            {"totals": totals, "leads": [lead]}, expected_schools=1
        )
        self.assertEqual(figures.staff_visits.target, 560)
        self.assertEqual(lead.readiness.schools_total, 1)
        self.assertEqual(people[0].readiness.staff_visits.remaining, 559)
        self.assertEqual(people[0].readiness.schools_to_recruit, 559)


class LedgerLineTests(SimpleTestCase):
    """Each planned activity lands in exactly one line of the ledger."""

    def row(self, **over):
        made = {
            "activity_type": "training_follow_up_visit",
            "purpose_type": "training_follow_up",
            "delivery_type": "staff",
            "school_id": "s1",
            "cluster_id": None,
            "responsible_staff_id": "p1",
            "project_id": None,
        }
        made.update(over)
        return made

    def key(self, **over):
        return readiness._ledger_key(self.row(**over), {"p1"}, {"s1"})

    def test_a_counted_visit_is_on_its_planners_row(self):
        self.assertEqual(self.key(), "staff_visit")

    def test_a_counted_visit_by_somebody_on_no_row_is_flagged(self):
        self.assertEqual(self.key(responsible_staff_id="rvp"), "off_roster")

    def test_a_partner_visit_follows_the_school(self):
        self.assertEqual(self.key(delivery_type="partner"), "partner_visit")
        self.assertEqual(
            self.key(delivery_type="partner", school_id="elsewhere"), "off_schools"
        )

    def test_a_partner_visit_at_a_school_that_takes_none_is_not_on_a_row(self):
        """A Champion school is on its holder's row and takes no visit: a
        Partner's visit there is on nobody's figures, and was filed with the
        Partner visits that are (2026-10-07 calculation check)."""
        partner = self.row(delivery_type="partner", school_id="champion")
        on_rows, take_a_visit = {"s1", "champion"}, {"s1"}
        self.assertEqual(
            readiness._ledger_key(partner, {"p1"}, on_rows, take_a_visit),
            "partner_no_visit_school",
        )
        self.assertEqual(
            readiness._ledger_key(
                self.row(delivery_type="partner"), {"p1"}, on_rows, take_a_visit
            ),
            "partner_visit",
        )

    def test_what_the_rulebook_leaves_out_says_why(self):
        # SSA Support is a counted visit when staff schedule it, and counted
        # nowhere when it is a Partner's (owner, 2026-10-03).
        ssa = {
            "activity_type": "school_visit_ssa_collection",
            "purpose_type": "ssa_support",
        }
        self.assertEqual(self.key(**ssa), "staff_visit")
        self.assertEqual(self.key(**ssa, delivery_type="partner"), "data_collection")
        self.assertEqual(
            self.key(activity_type="donor_visit", purpose_type="donor_visit"),
            "outreach",
        )
        self.assertEqual(
            self.key(purpose_type="in_school_training_delivery_visit"), "companion"
        )
        self.assertEqual(self.key(cluster_id="c1", school_id=None), "cluster")

    def test_the_flagged_lines_are_the_last_two(self):
        self.assertEqual(
            [key for key, _, flagged in readiness.LEDGER if flagged],
            ["off_roster", "off_schools"],
        )


class HandedToAPartnerIsNotUnplannedTests(SimpleTestCase):
    """Owner, 2026-10-03, read from the live monitor: 4,719 schools handed to
    Partners who had dated nothing read as "No visit", so a Lead with every
    school visited or handed over still showed 151 schools unplanned."""

    def test_a_school_awaiting_the_partners_date_is_covered(self):
        person = officer(
            [
                school(1, staff_visits=1),
                school(2, partner_pending=1),
                school(3),
            ],
            planned_client=1,
        )
        self.assertEqual(person.schools_with_visit, 1)
        self.assertEqual(person.schools_awaiting_partner, 1)
        # Country Planning Oversight's two figures, under their names.
        self.assertEqual((person.no_visit, person.unplanned), (2, 1))
        self.assertEqual(person.no_both, 1)
        self.assertEqual(
            dict((g["key"], n) for g, n in person.gap_cells)["no_visit"], 1
        )
        self.assertFalse(person.schools[1].has_gap("no_visit"))
        self.assertTrue(person.schools[2].has_gap("no_visit"))


class OwnerCountsOfOctoberThirdTests(SimpleTestCase):
    """Owner, 2026-10-03: "how many school the staff has scheduled for visits
    for themselves ... a column with the link of the schools scheduled by
    staff but also assigned to partner. For training look at inschool
    trainings and group trainings ... count all the schools attached"."""

    def setUp(self):
        self.person = officer(
            [
                school(1, staff_visits=1, group_training=True),
                school(2, staff_visits=2, partner_pending=1),
                school(3, partner_visits=1, in_school_training=True),
                school(4, meeting=True),
            ],
            planned_client=3,
        )
        self.figures = readiness.person_readiness(self.person)

    def test_schools_staff_scheduled_themselves(self):
        self.assertEqual(self.figures.schools_staff_scheduled, 2)
        self.assertEqual(
            [s.id for s in self.person.schools if s.has_gap("staff_scheduled")],
            ["s1", "s2"],
        )

    def test_schools_scheduled_by_staff_and_also_with_a_partner(self):
        self.assertEqual(self.figures.schools_staff_and_partner, 1)
        self.assertEqual(
            [s.id for s in self.person.schools if s.has_gap("staff_and_partner")],
            ["s2"],
        )

    def test_training_counts_schools_in_in_school_and_group_trainings(self):
        line = self.figures.staff_trainings
        self.assertEqual((line.planned, line.target, line.remaining), (2, 4, 2))

    def test_a_cluster_meeting_is_not_a_training(self):
        self.assertFalse(self.person.schools[3].has_training)
        self.assertTrue(self.person.schools[3].has_gap("no_training"))
        self.assertEqual(self.person.schools_meeting, 1)
