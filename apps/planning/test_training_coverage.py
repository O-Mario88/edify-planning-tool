"""Training coverage: a school assigned to a Partner counts from the hand-over.

Owner, 2026-10-08: "The training summary should not wait for partner
scheduling ... The assignment itself represents a legitimate planned/committed
school for training capacity purposes", and "Assigned ≠ Scheduled ≠ Completed
— but Assigned must still count toward training coverage/capacity."

What is pinned here: the owner's worked example (a ceiling of 20 with 5
planned by staff, 7 assigned to a Partner and 6 on a group training is 18
covered and 2 remaining, before the Partner has dated anything); that the
Partner dating a school moves it on and adds none; who a Partner's training
is filed under once it is an activity; that the ceiling is held by every
route; the list behind each figure, with its route, responsible person,
status and next action; and the schools not yet covered.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import Client

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.activities.services import partner_schedule
from apps.activity_catalogue.services import resolve_item_for_workflow_kind
from apps.core.enums import ActivityType
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.partners import services as partner_services
from apps.partners.models import Partner, PartnerAssignment
from apps.planning import training_ceilings, training_coverage, training_summary
from apps.schools.models import School

from .test_standard_support_scheduling import _at
from .test_training_ceilings import BACKEND, LEADERSHIP, CeilingFixture, _day


class CoverageFixture(CeilingFixture):
    """John, his Programme Lead, a Partner, and schools John holds."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.partner_user = User.objects.create_user(
            email="coverage-partner@edify.org",
            name="Partner Field Officer",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            password="x",
            is_active=True,
        )
        cls.partner = Partner.objects.create(
            name="Literacy Partner",
            user=cls.partner_user,
            active_status=True,
            contract_status="active",
            source="test",
        )
        cls.workflow = resolve_item_for_workflow_kind(ActivityType.IN_SCHOOL_TRAINING)
        # John holds his cluster's schools: the schools a list of "not yet
        # covered" is drawn from.
        School.objects.filter(id__in=[s.id for s in cls.members]).update(
            account_owner_id=cls.staff.id
        )

    def hand_over(self, school, *, code=LEADERSHIP, staff=None, partner=None):
        """A school handed to the Partner for an in-school training, as the
        Planning drawer hands it over."""
        staff = staff or self.staff
        course = self.item(code)
        return partner_services.create_assignment(
            school=school,
            partner=partner or self.partner,
            assigning_staff_id=staff.id,
            monitoring_staff_id=staff.id,
            assignment_mode="specific_activity",
            catalogue_item=self.workflow,
            training_course=course,
            catalogue_snapshot=self.workflow.snapshot(),
            purpose=course.display_name,
            purpose_of_visit="in_school_training",
            expected_activity_type="in_school_training",
        )

    def partner_dates(self, handover, day=0):
        """The Partner puts the hand-over on a day of its own."""
        with self.captureOnCommitCallbacks(execute=True):
            result = partner_schedule(
                handover.id,
                {
                    "scheduledDate": _at(_day(day)).isoformat(),
                    "deliveryContactName": "Partner Field Officer",
                },
                self.partner_user,
            )
        return Activity.objects.get(id=result["id"])

    def row(self, staff=None, training=None):
        staff = staff or self.staff
        training = training or self.leadership
        return next(
            row
            for row in training_ceilings.summary_for_staff([staff], self.fy)
            if row.training_id == training.id
        )

    def the_owner_s_example(self):
        """Ceiling 20: 5 planned by staff, 7 with the Partner, 6 on a group
        training. Returns the seven hand-overs."""
        self.ceiling(value=20)
        for index, school in enumerate(self.members[0:5]):
            self.in_school(school, day=index)
        handovers = [self.hand_over(school) for school in self.members[5:12]]
        self.group(self.members[12:18], day=6)
        return handovers


class AssignedCountsBeforeThePartnerSchedules(CoverageFixture):
    def test_the_summary_does_not_wait_for_the_partner(self):
        self.the_owner_s_example()

        row = self.row()

        self.assertEqual(
            (row.in_school, row.partner, row.group, row.total, row.balance),
            (5, 7, 6, 18, 2),
        )
        # None of the seven has a date yet: all are waiting on the Partner.
        self.assertEqual((row.partner_scheduled, row.awaiting_partner), (0, 7))
        self.assertEqual(row.excess, 0)

    def test_scheduling_moves_a_school_on_and_adds_none(self):
        handovers = self.the_owner_s_example()
        for index, handover in enumerate(handovers[:4]):
            self.partner_dates(handover, day=10 + index)

        row = self.row()

        # 5 + 7 + 6, never 5 + 7 + 4 + 6: the four are part of the seven.
        self.assertEqual((row.partner, row.partner_scheduled), (7, 4))
        self.assertEqual(row.awaiting_partner, 3)
        self.assertEqual((row.total, row.balance), (18, 2))

    def test_the_partner_s_training_stays_under_the_officer_who_follows_it(self):
        handover = self.hand_over(self.members[0])
        activity = self.partner_dates(handover)

        # The Partner's activity names no responsible officer; it is John's
        # by its monitor, as the hand-over was.
        self.assertIsNone(activity.responsible_staff_id)
        self.assertEqual(activity.delivery_type, "partner")
        row = self.row()
        self.assertEqual((row.partner, row.partner_scheduled, row.total), (1, 1, 1))
        self.assertEqual(self.row().in_school, 0)

    def test_a_school_on_two_routes_is_one_school(self):
        school = self.members[0]
        self.in_school(school)
        self.group([school, self.members[1]], day=1)
        # Staff's own in-school training and a hand-over at one school: the
        # door refuses that hand-over since the one-visit rule (owner,
        # 2026-10-08; `_assert_school_has_room`), and plans made before it
        # are left as they are, so the count still meets them. This is one of
        # those: the hand-over as the door made it, the rule's check aside.
        with patch("apps.partners.services._assert_school_has_room"):
            self.hand_over(school)

        row = self.row()

        self.assertEqual((row.in_school, row.group, row.partner), (1, 2, 1))
        self.assertEqual(row.total, 2)

    def test_a_hand_over_the_partner_let_go_leaves_the_count(self):
        handover = self.hand_over(self.members[0])
        self.hand_over(self.members[1])
        PartnerAssignment.objects.filter(id=handover.id).update(
            status=PartnerAssignment.STATUS_RETURNED_TO_STAFF
        )

        self.assertEqual(self.row().partner, 1)

    def test_a_hand_over_for_a_visit_is_not_a_training(self):
        partner_services.create_assignment(
            school=self.members[0],
            partner=self.partner,
            assigning_staff_id=self.staff.id,
            monitoring_staff_id=self.staff.id,
            purpose_of_visit="follow_up",
            expected_activity_type="school_visit",
        )

        self.assertEqual(training_ceilings.summary_for_staff([self.staff], self.fy), [])

    def test_a_waiting_hand_over_is_read_now_and_ahead_never_in_a_closed_year(self):
        from apps.core.fy import get_operational_fy

        running = int(get_operational_fy())
        self.assertTrue(training_ceilings.handovers_read_in(str(running)))
        self.assertTrue(training_ceilings.handovers_read_in(str(running + 1)))
        self.assertFalse(training_ceilings.handovers_read_in(str(running - 1)))

    def test_the_country_counts_the_partner_s_schools(self):
        handovers = self.the_owner_s_example()
        self.partner_dates(handovers[0], day=10)

        country = training_ceilings.country_scheduled(self.fy, "Uganda")[
            self.leadership.id
        ]

        self.assertEqual(
            country,
            {
                "group": 6,
                "in_school": 5,
                "partner": 7,
                "partner_scheduled": 1,
                "awaiting_partner": 6,
                "total": 18,
            },
        )

    def test_the_summary_table_reads_the_same_schools(self):
        self.the_owner_s_example()
        TrainingCountryCeilingFor = training_ceilings.set_country_ceiling
        admin = User.objects.create_user(
            email="coverage-admin@edify.org",
            name="Admin Ada",
            roles=["Admin"],
            active_role="Admin",
            password="x",
            is_active=True,
        )
        TrainingCountryCeilingFor(
            admin, training_id=self.leadership.id, fy=self.fy, ceiling=20
        )

        summary = training_summary.for_reader(self.pl, self.fy)
        row = next(r for r in summary.rows if r.training_id == self.leadership.id)

        self.assertEqual((row.planned, row.remaining), (18, 2))
        self.assertEqual(
            (row.staff_planned, row.partner, row.awaiting_partner, row.group),
            (5, 7, 7, 6),
        )
        john = next(c for c in row.cells if c.staff_id == self.staff.id)
        self.assertEqual((john.schools, john.limit), (18, 20))
        self.assertEqual((john.partner, john.awaiting_partner), (7, 7))


class CancelledWorkLeavesTheCoverage(CoverageFixture):
    """A cancelled activity undoes the scheduling (owner, 2026-10-08): a
    partner's school goes back to waiting, staff's own leaves the count."""

    REASON = {"reason": "The school asked for another week."}

    def test_a_partner_s_cancelled_date_is_assigned_and_awaiting_again(self):
        from apps.activities.services import cancel

        handover = self.hand_over(self.members[0])
        activity = self.partner_dates(handover)
        self.assertEqual((self.row().partner, self.row().partner_scheduled), (1, 1))

        with self.captureOnCommitCallbacks(execute=True):
            cancel(activity.id, self.REASON, self.partner_user)

        row = self.row()
        self.assertEqual(
            (row.partner, row.partner_scheduled, row.awaiting_partner, row.total),
            (1, 0, 1, 1),
        )
        rows = training_coverage.schools_behind(
            self.pl,
            staff_id=self.staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
        )["rows"]
        self.assertEqual(
            [(r.status_label, r.next_action) for r in rows],
            [("Partner Assigned — Awaiting Schedule", "Partner to schedule")],
        )

    def test_a_cancelled_staff_training_frees_its_place(self):
        from apps.activities import pairs

        self.ceiling(value=1)
        training = self.in_school(self.members[0])
        self.assertEqual(self.row().balance, 0)

        with self.captureOnCommitCallbacks(execute=True):
            pairs.cancel(training.id, self.REASON, self.user)

        row = self.row()
        self.assertEqual((row.in_school, row.total, row.balance), (0, 0, 1))
        # The place is free: another school is planned under the ceiling.
        self.in_school(self.members[1], day=1)
        self.assertEqual(self.row().total, 1)


class TheCeilingIsHeldByEveryRoute(CoverageFixture):
    def test_schools_with_a_partner_take_places_staff_cannot_plan_past(self):
        self.ceiling(value=3)
        for school in self.members[0:3]:
            self.hand_over(school)

        with self.assertRaises(BadRequest) as refused:
            self.in_school(self.members[3])

        message = str(refused.exception.detail)
        self.assertIn("Training ceiling reached", message)
        self.assertIn("3 are already covered", message)

    def test_a_hand_over_past_the_ceiling_is_refused(self):
        self.ceiling(value=2)
        self.in_school(self.members[0])
        self.in_school(self.members[1], day=1)

        with self.assertRaises(BadRequest) as refused:
            self.hand_over(self.members[2])

        self.assertIn("Training ceiling reached", str(refused.exception.detail))
        self.assertFalse(
            PartnerAssignment.objects.filter(school=self.members[2]).exists()
        )

    def test_a_school_already_covered_is_handed_over_at_the_ceiling(self):
        self.ceiling(value=2)
        self.in_school(self.members[0])
        self.group([self.members[1]], day=1)

        # On the group training already: the hand-over adds no school.
        self.hand_over(self.members[1])

        self.assertEqual(self.row().total, 2)

    def test_the_partner_dating_it_takes_no_second_place(self):
        self.ceiling(value=1)
        handover = self.hand_over(self.members[0])

        self.partner_dates(handover)

        row = self.row()
        self.assertEqual((row.total, row.balance, row.excess), (1, 0, 0))

    def test_with_no_ceiling_a_hand_over_is_never_refused(self):
        for school in self.members[0:4]:
            self.hand_over(school)

        self.assertEqual(self.row().partner, 4)

    def test_the_drawer_reads_the_partner_s_schools_as_covered(self):
        self.ceiling(value=5)
        self.in_school(self.members[0])
        handover = self.hand_over(self.members[1])
        self.hand_over(self.members[2])
        self.partner_dates(handover, day=2)

        capacity = training_ceilings.capacity(
            self.staff.id, self.leadership.id, self.fy
        )

        self.assertEqual((capacity["scheduled"], capacity["remaining"]), (3, 2))
        self.assertEqual(
            (
                capacity["inSchool"],
                capacity["partner"],
                capacity["partnerScheduled"],
                capacity["awaitingPartner"],
            ),
            (1, 2, 1, 1),
        )
        self.assertEqual(set(capacity["schoolIds"]), {s.id for s in self.members[0:3]})


class TheSchoolsBehindEachFigure(CoverageFixture):
    def behind(self, figure="", **extra):
        return training_coverage.schools_behind(
            self.pl,
            staff_id=self.staff.id,
            training_id=self.leadership.id,
            fy=self.fy,
            figure=figure,
            **extra,
        )

    def test_each_figure_opens_the_schools_it_counts(self):
        handovers = self.the_owner_s_example()
        for index, handover in enumerate(handovers[:4]):
            self.partner_dates(handover, day=10 + index)

        counts = {
            figure: self.behind(figure)["school_count"]
            for figure in (
                "covered",
                "staff",
                "partner",
                "partner_scheduled",
                "awaiting",
                "group",
            )
        }

        self.assertEqual(
            counts,
            {
                "covered": 18,
                "staff": 5,
                "partner": 7,
                "partner_scheduled": 4,
                "awaiting": 3,
                "group": 6,
            },
        )
        # The older links still open their schools.
        self.assertEqual(self.behind(delivery="group")["school_count"], 6)
        self.assertEqual(self.behind(delivery="in_school")["school_count"], 12)

    def test_a_row_says_who_is_responsible_and_what_it_waits_on(self):
        self.in_school(self.members[0])
        waiting = self.hand_over(self.members[1])
        dated = self.hand_over(self.members[2])
        self.partner_dates(dated, day=2)
        self.group([self.members[3]], day=3)

        rows = {row.school_pk: row for row in self.behind()["rows"]}

        staff_row = rows[self.members[0].id]
        self.assertEqual(
            (
                staff_row.route_label,
                staff_row.responsible,
                staff_row.status_label,
                staff_row.next_action,
            ),
            ("In-School · Staff", self.staff.user.name, "Staff Planned", "Conduct"),
        )
        waiting_row = rows[self.members[1].id]
        self.assertEqual(
            (
                waiting_row.route_label,
                waiting_row.responsible,
                waiting_row.status_label,
                waiting_row.next_action,
                waiting_row.scheduled,
                waiting_row.assignment_id,
            ),
            (
                "In-School · Partner",
                "Literacy Partner",
                "Partner Assigned — Awaiting Schedule",
                "Partner to schedule",
                False,
                waiting.id,
            ),
        )
        dated_row = rows[self.members[2].id]
        self.assertEqual(
            (dated_row.status_label, dated_row.next_action, dated_row.scheduled),
            ("Partner Scheduled", "Partner to conduct", True),
        )
        group_row = rows[self.members[3].id]
        self.assertEqual(
            (group_row.route_label, group_row.status_label, group_row.cluster),
            ("Group Training", "Group Scheduled", "Standard Cluster"),
        )

    def test_delivery_moves_a_school_to_in_progress_and_completed(self):
        started = self.in_school(self.members[0])
        done = self.in_school(self.members[1], day=1)
        Activity.objects.filter(id=started.id).update(status="evidence_uploaded")
        Activity.objects.filter(id=done.id).update(status="ia_verified")

        result = self.behind()
        rows = {row.school_pk: row for row in result["rows"]}

        self.assertEqual(rows[self.members[0].id].status_label, "In Progress")
        self.assertEqual(rows[self.members[1].id].status_label, "Completed")
        self.assertEqual(rows[self.members[1].id].next_action, "None")
        self.assertEqual(
            result["progress"], {"scheduled": 2, "started": 2, "completed": 1}
        )

    def test_remaining_lists_the_schools_not_yet_covered(self):
        self.in_school(self.members[0])
        self.hand_over(self.members[1])
        self.group([self.members[2]], day=2)

        result = self.behind("remaining")

        covered = {s.id for s in self.members[0:3]}
        listed = {row.school_pk for row in result["rows"]}
        self.assertEqual(listed, {s.id for s in self.members} - covered)
        self.assertEqual(result["school_count"], len(self.members) - 3)
        first = result["rows"][0]
        self.assertEqual(
            (first.status_label, first.next_action, first.route_label),
            ("Not Covered", "Plan", "—"),
        )

    def test_a_closed_or_champion_school_is_not_waiting_to_be_covered(self):
        School.objects.filter(id=self.members[0].id).update(school_type="champion")
        School.objects.filter(id=self.members[1].id).update(operational_status="closed")

        listed = {row.school_pk for row in self.behind("remaining")["rows"]}

        self.assertNotIn(self.members[0].id, listed)
        self.assertNotIn(self.members[1].id, listed)

    def test_every_training_a_person_has_schools_for_in_one_list(self):
        self.in_school(self.members[0])
        self.hand_over(self.members[1], code="SSA_TRAINING")

        result = training_coverage.schools_behind(
            self.user, staff_id=self.staff.id, fy=self.fy
        )

        self.assertTrue(result["show_training"])
        self.assertEqual(
            {row.training_name for row in result["rows"]},
            {self.leadership.display_name, self.improvement.display_name},
        )


class TheCoverageTable(CoverageFixture):
    def test_it_lists_every_commitment_and_the_uncovered_for_one_training(self):
        self.in_school(self.members[0])
        self.hand_over(self.members[1])
        self.group([self.members[2]], day=2)

        every = training_coverage.table([self.staff, self.mary_staff], self.fy)
        self.assertEqual(every["school_count"], 3)
        self.assertEqual(
            [(c["key"], c["count"]) for c in every["counts"]],
            [("staff_planned", 1), ("partner_assigned", 1), ("group_scheduled", 1)],
        )

        one = training_coverage.table(
            [self.staff], self.fy, training_id=self.leadership.id
        )
        statuses = {row.status for row in one["rows"]}
        self.assertIn("not_covered", statuses)
        self.assertEqual(one["school_count"], len(self.members))

        waiting = training_coverage.table(
            [self.staff], self.fy, training_id=self.leadership.id, show="awaiting"
        )
        self.assertEqual(
            [row.school_pk for row in waiting["rows"]], [self.members[1].id]
        )


class ThePagesShowIt(CoverageFixture):
    def client_for(self, user):
        client = Client()
        client.force_login(user, backend=BACKEND)
        return client

    def test_my_plan_names_each_route_and_links_each_figure(self):
        handovers = self.the_owner_s_example()
        self.partner_dates(handovers[0], day=10)

        response = self.client_for(self.user).get(f"/my-plan?fy={self.fy}")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for heading in (
            "Staff<br>Planned",
            "Partner<br>Assigned",
            "Awaiting<br>Partner",
            "Group<br>Scheduled",
            "Schools<br>Covered",
            "Remaining",
        ):
            self.assertIn(heading, html)
        for figure in ("staff", "partner", "awaiting", "group", "covered", "remaining"):
            self.assertIn(f'data-summary-figure="{figure}"', html)

    def test_the_drawer_lists_the_schools_awaiting_the_partner(self):
        handovers = self.the_owner_s_example()
        self.partner_dates(handovers[0], day=10)

        response = self.client_for(self.user).get(
            "/training-summary/schools",
            {
                "staff": self.staff.id,
                "training": self.leadership.id,
                "fy": self.fy,
                "figure": "awaiting",
            },
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Awaiting partner scheduling", html)
        self.assertIn("Partner to schedule", html)
        self.assertIn("Literacy Partner", html)
        self.assertEqual(html.count("data-coverage-row"), 6)

    def test_the_lead_reads_the_team_s_coverage_by_staff_and_by_school(self):
        self.the_owner_s_example()
        client = self.client_for(self.pl)

        by_staff = client.get(
            f"/team-planning-oversight/?view=trainings&tab=staff&fy={self.fy}"
        )
        self.assertEqual(by_staff.status_code, 200)
        html = by_staff.content.decode()
        self.assertIn("data-training-coverage-by-staff", html)
        self.assertIn(self.staff.user.name, html)

        schools = client.get(
            "/team-planning-oversight/",
            {
                "view": "trainings",
                "tab": "schools",
                "fy": self.fy,
                "training": self.leadership.id,
                "show": "awaiting",
            },
        )
        self.assertEqual(schools.status_code, 200)
        html = schools.content.decode()
        self.assertIn("data-training-coverage-table", html)
        self.assertEqual(html.count("data-coverage-row"), 7)
        self.assertIn("Partner Assigned — Awaiting Schedule", html)

    def test_a_country_reader_opens_the_schools_behind_a_country_figure(self):
        handovers = self.the_owner_s_example()
        self.partner_dates(handovers[0], day=10)
        director = self._person(
            "coverage-cd@edify.org", "Dora Director", "CountryDirector"
        )[0]
        client = self.client_for(director)

        summary = client.get(f"/team-planning-oversight/?view=trainings&fy={self.fy}")
        self.assertEqual(summary.status_code, 200)
        html = summary.content.decode()
        for figure in ("staff", "partner", "awaiting", "group", "covered"):
            self.assertIn(f'data-summary-figure="country-{figure}"', html)
        self.assertIn('data-summary-figure="country-remaining"', html)

        # The list is as long as the figure: six still wait for the Partner.
        schools = client.get(
            "/team-planning-oversight/",
            {
                "view": "trainings",
                "tab": "schools",
                "fy": self.fy,
                "training": self.leadership.id,
                "show": "awaiting",
            },
        )
        self.assertEqual(schools.status_code, 200)
        self.assertEqual(schools.content.decode().count("data-coverage-row"), 6)

    def test_a_lead_reads_the_country_s_figures_and_opens_their_own_team_s(self):
        self.the_owner_s_example()

        html = (
            self.client_for(self.pl)
            .get(f"/team-planning-oversight/?view=trainings&fy={self.fy}")
            .content.decode()
        )

        # The country's figures are on the row; the Lead's links are the
        # staff columns, which open their own officers' schools.
        self.assertIn("data-country-partner", html)
        self.assertNotIn('data-summary-figure="country-', html)
        self.assertIn('data-summary-figure="training"', html)
