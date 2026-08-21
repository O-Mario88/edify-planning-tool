"""Partner oversight: one item per handover, and no cost before scheduling.

The two rules this file exists to hold are the ones a supervisor would act on
wrongly if they broke — a doubled row inflates how much work a partner owes,
and a cost shown before anyone agreed a date invites planning around money that
does not exist.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.planning import partner_oversight_service as svc
from apps.schools.models import School


class PartnerOversightFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.pl_user, cls.pl = cls._staff(
            "mary@p.test", "Mary", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.cceo_user, cls.cceo = cls._staff("james@p.test", "James", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(supervisee=cls.cceo, supervisor=cls.pl)

        cls.rival_pl_user, cls.rival_pl = cls._staff(
            "other@p.test", "Other Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.rival_cceo_user, cls.rival_cceo = cls._staff(
            "rival@p.test", "Rival", EdifyRole.CCEO
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.rival_cceo, supervisor=cls.rival_pl
        )

        cls.school = School.objects.create(
            school_id="s1", name="School A", district=cls.district, region=cls.region
        )
        cls.rival_school = School.objects.create(
            school_id="s2",
            name="Rival School",
            district=cls.district,
            region=cls.region,
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo, school_id=cls.school.id)
        cls.partner = Partner.objects.create(name="Partner X", active_status=True)
        cls.other_partner = Partner.objects.create(name="Partner Y", active_status=True)

    @classmethod
    def _staff(cls, email, name, role):
        user = User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title=name)

    def assign(self, *, school=None, cceo=None, partner=None, status="assigned", **kw):
        return PartnerAssignment.objects.create(
            school=school or self.school,
            partner=partner or self.partner,
            assigning_staff_id=(cceo or self.cceo).id,
            monitoring_staff_id=(cceo or self.cceo).id,
            expected_activity_type="school_visit",
            focus_intervention="financial_health",
            status=status,
            **kw,
        )

    def schedule(
        self, assignment, *, cost=180_000, when=None, status="partner_scheduled"
    ):
        """What the partner's scheduling produces: one activity, priced."""
        planned = when or (date.today() + timedelta(days=5))
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=assignment.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=planned,
            planned_month=planned.month,
            status=status,
            delivery_type="partner",
            assigned_partner_id=assignment.partner_id,
            monitored_by_staff_id=assignment.monitoring_staff_id,
        )
        if cost:
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                cost_setting_key="partner_visit_lump_sum",
                label="Partner visit",
                unit_cost=cost,
                quantity=1,
                amount=cost,
            )
        assignment.status = "partner_scheduled"
        assignment.scheduled_activity = activity
        assignment.scheduled_date = planned
        assignment.save()
        return activity


class OneItemPerHandoverTest(PartnerOversightFixture):
    def test_an_unscheduled_handover_is_one_item_awaiting_the_partner(self):
        self.assign()

        items = svc.build_items(self.pl_user, fy=self.fy)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].stage, svc.STAGE_AWAITING_SCHEDULE)
        self.assertEqual(items[0].next_action_owner, "Partner X")

    def test_scheduling_enriches_the_same_item_rather_than_adding_one(self):
        assignment = self.assign()
        activity = self.schedule(assignment)

        items = svc.build_items(self.pl_user, fy=self.fy)

        self.assertEqual(len(items), 1, "the handover and its delivery are one item")
        self.assertEqual(items[0].partner_assignment_id, assignment.id)
        self.assertEqual(items[0].partner_activity_id, activity.id)
        self.assertTrue(items[0].is_scheduled)

    def test_two_handovers_to_one_partner_at_one_school_stay_distinct(self):
        """The case a partner+school match would collapse into one."""
        first = self.assign()
        second = self.assign()
        self.schedule(first)

        items = svc.build_items(self.pl_user, fy=self.fy)

        self.assertEqual(len(items), 2)
        self.assertEqual(
            {i.partner_assignment_id for i in items}, {first.id, second.id}
        )


class CostAppearsOnlyAfterSchedulingTest(PartnerOversightFixture):
    def test_an_unscheduled_handover_has_no_cost_at_all(self):
        """Absent, not zero: nobody has agreed a price for work with no date."""
        self.assign()

        item = svc.build_items(self.pl_user, fy=self.fy)[0]

        self.assertIsNone(item.planned_cost)
        self.assertFalse(item.has_cost)

    def test_the_scheduled_budget_excludes_unscheduled_handovers(self):
        self.assign()
        self.schedule(self.assign(), cost=180_000)

        summary = svc.summarize(svc.build_items(self.pl_user, fy=self.fy))

        self.assertEqual(summary["scheduled_budget"], 180_000)
        self.assertEqual(summary["awaiting_schedule"], 1)

    def test_the_cost_equals_the_source_lines_and_records_its_catalogue(self):
        assignment = self.assign()
        activity = self.schedule(assignment, cost=95_000)

        item = svc.build_items(self.pl_user, fy=self.fy)[0]

        from django.db.models import Sum

        source = ActivityScheduleCostLine.objects.filter(activity=activity).aggregate(
            t=Sum("amount")
        )["t"]
        self.assertEqual(item.planned_cost, source)
        self.assertTrue(item.has_cost)

    def test_a_returned_handover_carries_no_cost(self):
        self.assign(status="returned_to_staff", return_reason="No capacity this term")

        item = svc.build_items(self.pl_user, fy=self.fy)[0]

        self.assertTrue(item.is_returned)
        self.assertIsNone(item.planned_cost)
        self.assertEqual(item.next_action_owner, "James")


class ScopeTest(PartnerOversightFixture):
    def test_the_supervising_program_lead_sees_the_handover(self):
        self.assign()

        items = svc.build_items(self.pl_user, fy=self.fy)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].supervising_pl_id, self.pl.id)
        self.assertEqual(items[0].responsible_cceo_name, "James")

    def test_another_program_lead_never_sees_it(self):
        self.assign()

        self.assertEqual(svc.build_items(self.rival_pl_user, fy=self.fy), [])

    def test_grouping_is_by_partner(self):
        self.assign(partner=self.partner)
        self.assign(partner=self.other_partner)

        groups = svc.group_by_partner(svc.build_items(self.pl_user, fy=self.fy))

        self.assertEqual([g["name"] for g in groups], ["Partner X", "Partner Y"])
        self.assertEqual(sum(len(g["items"]) for g in groups), 2)

    def test_group_summaries_add_up_to_the_whole(self):
        self.schedule(self.assign(partner=self.partner), cost=100_000)
        self.schedule(self.assign(partner=self.other_partner), cost=50_000)

        items = svc.build_items(self.pl_user, fy=self.fy)
        whole = svc.summarize(items)
        groups = svc.group_by_partner(items)

        self.assertEqual(
            sum(g["summary"]["scheduled_budget"] for g in groups),
            whole["scheduled_budget"],
        )


class NextActionOwnerTest(PartnerOversightFixture):
    def test_the_owner_moves_along_the_workflow(self):
        assignment = self.assign()
        item = svc.build_items(self.pl_user, fy=self.fy)[0]
        self.assertEqual(item.next_action_owner, "Partner X")

        activity = self.schedule(assignment)
        activity.status = "evidence_uploaded"
        activity.evidence_status = "uploaded"
        activity.save()
        item = svc.build_items(self.pl_user, fy=self.fy)[0]
        # §10 direct IA handoff: evidence captured but unsubmitted is the
        # PARTNER's move (submit to IA) — no CCEO review stage exists.
        self.assertEqual(item.next_action_owner, "Partner X")
        self.assertIn("evidence", item.next_action.lower())

        activity.status = "salesforce_id_required"
        activity.save()
        item = svc.build_items(self.pl_user, fy=self.fy)[0]
        self.assertIn("Salesforce", item.next_action)

        activity.status = "ia_verified"
        activity.salesforce_activity_id = "SF-1"
        activity.save()
        item = svc.build_items(self.pl_user, fy=self.fy)[0]
        self.assertEqual(item.next_action_owner, "Accountant")

    def test_there_is_exactly_one_next_action(self):
        self.schedule(self.assign())

        item = svc.build_items(self.pl_user, fy=self.fy)[0]

        self.assertTrue(item.next_action)
        self.assertTrue(item.next_action_owner)


class QueryBudgetTest(PartnerOversightFixture):
    def test_the_cost_is_fixed_rather_than_one_query_per_handover(self):
        for _ in range(10):
            self.schedule(self.assign(), cost=10_000)
        for _ in range(5):
            self.assign()

        with CaptureQueriesContext(connection) as captured:
            items = svc.build_items(self.pl_user, fy=self.fy)
            svc.summarize(items)
            svc.group_by_partner(items)
        baseline = len(captured)

        self.assertEqual(len(items), 15)

        # The property that matters is that the cost does not grow with the
        # number of handovers — a fixed count, not a low one. Most of the
        # baseline is scope resolution, which happens once per page load.
        for _ in range(20):
            self.schedule(self.assign(), cost=5_000)

        with CaptureQueriesContext(connection) as captured_larger:
            larger = svc.build_items(self.pl_user, fy=self.fy)
            svc.summarize(larger)
            svc.group_by_partner(larger)

        self.assertEqual(len(larger), 35)
        self.assertEqual(
            len(captured_larger),
            baseline,
            "query count grew with the number of handovers",
        )


class PartnerWorkReachesItsSupervisorsTest(PartnerOversightFixture):
    """Owning the school or cluster is what makes partner work visible.

    A partner-delivered activity carries no responsible staff member by
    construction, and `monitored_by_staff_id` records whoever happened to be
    resolved at handoff. Scoping planning oversight on those two columns alone
    meant a school's own CCEO saw 6 of the 233 partner activities running in
    their portfolio, and a Program Lead — who supervises rather than owns —
    saw none at all. Both were reading a page whose whole purpose is watching
    partner delivery.
    """

    def _partner_activity_monitored_by_someone_else(self):
        """The realistic shape: handed off by a colleague, not by the owner."""
        assignment = self.assign()
        activity = self.schedule(assignment)
        # Both legacy columns empty, which is the case the ownership arms
        # exist for: `monitoring_staff_id` is nullable and every row written
        # before it existed has none, so nothing but ownership can reach this.
        Activity.objects.filter(id=activity.id).update(
            responsible_staff_id=None,
            monitored_by_staff_id=None,
        )
        School.objects.filter(id=self.school.id).update(
            account_owner_id=self.cceo.id
        )
        return activity

    def _partner_items(self, user):
        from apps.planning import oversight_service

        return [
            item
            for item in oversight_service.build_items(user, fy=self.fy)
            if item.is_partner_work and item.activity_id
        ]

    def test_the_school_owner_sees_partner_work_they_did_not_hand_off(self):
        activity = self._partner_activity_monitored_by_someone_else()

        found = self._partner_items(self.cceo_user)

        self.assertEqual([i.activity_id for i in found], [activity.id])

    def test_the_supervising_program_lead_sees_it_too(self):
        activity = self._partner_activity_monitored_by_someone_else()

        found = self._partner_items(self.pl_user)

        self.assertEqual([i.activity_id for i in found], [activity.id])

    def test_an_unrelated_program_lead_still_sees_nothing(self):
        self._partner_activity_monitored_by_someone_else()

        found = self._partner_items(self.rival_pl_user)

        self.assertEqual([i.activity_id for i in found], [])
