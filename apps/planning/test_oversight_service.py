"""The invariants planning oversight is only trustworthy if it holds.

These are about arithmetic and attribution rather than presentation: a page
that shows a Program Lead another team's work, or a country budget that does
not equal the cost lines it was folded from, is worse than no page at all
because it looks authoritative.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.planning import oversight_service as svc
from apps.schools.models import School


class OversightFixture(TestCase):
    """One Program Lead, two supervised CCEOs, one partner, one rival team."""

    @classmethod
    def setUpTestData(cls):
        cls.fy = "2026"
        cls.region = Region.objects.create(id="reg-1", name="Central")
        cls.district = District.objects.create(
            id="dist-1", name="Kampala", region=cls.region
        )

        cls.pl_user, cls.pl = cls._staff(
            "pl@edify.test", "Team Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.james_user, cls.james = cls._staff(
            "james@edify.test", "James", EdifyRole.CCEO
        )
        cls.mary_user, cls.mary = cls._staff("mary@edify.test", "Mary", EdifyRole.CCEO)
        for supervisee in (cls.james, cls.mary):
            StaffSupervisorAssignment.objects.create(
                supervisee=supervisee, supervisor=cls.pl
            )

        # A second, unrelated team. Nothing of theirs may ever reach PL A.
        cls.rival_pl_user, cls.rival_pl = cls._staff(
            "rival@edify.test", "Other Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.rival_cceo_user, cls.rival_cceo = cls._staff(
            "rival-cceo@edify.test", "Rival CCEO", EdifyRole.CCEO
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.rival_cceo, supervisor=cls.rival_pl
        )

        cls.cd_user, cls.cd = cls._staff(
            "cd@edify.test", "Director", EdifyRole.COUNTRY_DIRECTOR
        )

        cls.school_a = cls._school("sch-a", "Alpha Primary")
        cls.school_b = cls._school("sch-b", "Beta Primary")
        cls.school_r = cls._school("sch-r", "Rival Primary")
        # school_id is a plain CharField on this join, not a FK.
        StaffSchoolAssignment.objects.create(staff=cls.james, school_id=cls.school_a.id)
        StaffSchoolAssignment.objects.create(staff=cls.mary, school_id=cls.school_b.id)
        StaffSchoolAssignment.objects.create(
            staff=cls.rival_cceo, school_id=cls.school_r.id
        )

        cls.partner = Partner.objects.create(name="Partner X", active_status=True)

    @classmethod
    def _staff(cls, email, name, role):
        user = User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            is_active=True,
        )
        profile = StaffProfile.objects.create(user=user, title=name)
        return user, profile

    @classmethod
    def _school(cls, school_id, name):
        return School.objects.create(
            school_id=school_id, name=name, district=cls.district, region=cls.region
        )

    def _activity(
        self,
        *,
        owner,
        school,
        cost=0,
        partner=None,
        monitored_by=None,
        status="scheduled",
        planned=None,
    ):
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=school,
            fy=self.fy,
            quarter="Q1",
            planned_date=planned or (date.today() + timedelta(days=7)),
            planned_month=(planned or (date.today() + timedelta(days=7))).month,
            status=status,
            responsible_staff_id=owner.id if owner else None,
            monitored_by_staff_id=monitored_by.id if monitored_by else None,
            assigned_partner_id=partner.id if partner else None,
        )
        if cost:
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                cost_setting_key="visit_transport",
                label="Transport",
                unit_cost=cost,
                quantity=1,
                amount=cost,
            )
        return activity

    def _assignment(self, *, school, managing_staff, status="assigned"):
        return PartnerAssignment.objects.create(
            school=school,
            partner=self.partner,
            assigning_staff_id=managing_staff.id,
            monitoring_staff_id=managing_staff.id,
            expected_activity_type="school_visit",
            status=status,
        )


class ProgramLeadScopeTest(OversightFixture):
    def test_the_program_lead_sees_own_work_and_supervised_work(self):
        self._activity(owner=self.pl, school=self.school_a)
        self._activity(owner=self.james, school=self.school_a)
        self._activity(owner=self.mary, school=self.school_b)

        items = svc.build_items(self.pl_user, fy=self.fy)

        self.assertEqual(len(items), 3)
        owners = {i.operational_owner_id for i in items}
        self.assertEqual(owners, {self.pl.id, self.james.id, self.mary.id})

    def test_another_teams_work_never_appears(self):
        self._activity(owner=self.james, school=self.school_a)
        self._activity(owner=self.rival_cceo, school=self.school_r)

        items = svc.build_items(self.pl_user, fy=self.fy)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].operational_owner_id, self.james.id)

    def test_own_work_stays_separate_from_team_work(self):
        """A supervision page must not become a personal-performance total."""
        self._activity(owner=self.pl, school=self.school_a)
        self._activity(owner=self.james, school=self.school_a)
        self._assignment(school=self.school_b, managing_staff=self.mary)

        scope = svc.resolve_oversight_scope(self.pl_user)
        split = svc.split_own_and_team(svc.build_items(self.pl_user, fy=self.fy), scope)

        self.assertEqual(len(split["own"]), 1)
        self.assertEqual(len(split["cceo"]), 1)
        self.assertEqual(len(split["partner"]), 1)

    def test_each_item_carries_its_supervising_program_lead(self):
        self._activity(owner=self.james, school=self.school_a)

        item = svc.build_items(self.pl_user, fy=self.fy)[0]

        self.assertEqual(item.supervising_pl_id, self.pl.id)
        self.assertEqual(item.supervising_pl_name, "Team Lead")


class PartnerAssignmentTest(OversightFixture):
    def test_an_unscheduled_assignment_reads_as_awaiting_the_partner(self):
        self._assignment(school=self.school_a, managing_staff=self.james)

        item = svc.build_items(self.pl_user, fy=self.fy)[0]

        self.assertTrue(item.is_awaiting_partner_schedule)
        self.assertEqual(item.executor_type, svc.EXECUTOR_PARTNER)
        self.assertEqual(item.partner_name, "Partner X")

    def test_an_unscheduled_assignment_contributes_no_money(self):
        """Nothing is scheduled, so nothing is priced, so the plan holds UGX 0."""
        self._assignment(school=self.school_a, managing_staff=self.james)

        summary = svc.summarize(svc.build_items(self.pl_user, fy=self.fy))

        self.assertEqual(summary["planned_budget"], 0)
        self.assertEqual(summary["partner_awaiting_schedule"], 1)
        self.assertEqual(summary["scheduled_total"], 0)

    def test_a_scheduled_assignment_and_its_activity_are_one_item(self):
        """The case the whole no-double-count rule exists for."""
        activity = self._activity(
            owner=None,
            school=self.school_a,
            partner=self.partner,
            monitored_by=self.james,
            cost=90_000,
            status="partner_scheduled",
        )
        assignment = self._assignment(school=self.school_a, managing_staff=self.james)
        assignment.status = "partner_scheduled"
        assignment.scheduled_activity = activity
        assignment.save()

        items = svc.build_items(self.pl_user, fy=self.fy)
        summary = svc.summarize(items)

        self.assertEqual(len(items), 1, "the assignment and its activity are one item")
        self.assertEqual(items[0].activity_id, activity.id)
        self.assertEqual(summary["partner_scheduled"], 1)
        self.assertEqual(summary["partner_awaiting_schedule"], 0)
        self.assertEqual(summary["planned_budget"], 90_000)

    def test_partner_work_is_never_attributed_to_staff_execution(self):
        self._activity(
            owner=None,
            school=self.school_a,
            partner=self.partner,
            monitored_by=self.james,
            status="partner_scheduled",
        )

        item = svc.build_items(self.pl_user, fy=self.fy)[0]

        self.assertEqual(item.executor_type, svc.EXECUTOR_PARTNER)
        self.assertEqual(item.managing_staff_id, self.james.id)
        self.assertEqual(item.operational_owner_id, self.james.id)


class SummaryEqualsDetailTest(OversightFixture):
    def test_the_budget_equals_the_sum_of_the_cost_lines(self):
        self._activity(owner=self.james, school=self.school_a, cost=120_000)
        self._activity(owner=self.mary, school=self.school_b, cost=80_000)
        self._assignment(school=self.school_a, managing_staff=self.james)

        items = svc.build_items(self.pl_user, fy=self.fy)
        summary = svc.summarize(items)

        from django.db.models import Sum

        source_total = ActivityScheduleCostLine.objects.aggregate(t=Sum("amount"))["t"]
        self.assertEqual(summary["planned_budget"], source_total)
        self.assertEqual(summary["planned_budget"], sum(i.planned_cost for i in items))

    def test_group_summaries_add_up_to_the_whole(self):
        self._activity(owner=self.james, school=self.school_a, cost=50_000)
        self._activity(owner=self.mary, school=self.school_b, cost=25_000)

        items = svc.build_items(self.pl_user, fy=self.fy)
        whole = svc.summarize(items)
        groups = svc.group_by_owner(items)

        self.assertEqual(
            sum(g["summary"]["planned_budget"] for g in groups), whole["planned_budget"]
        )
        self.assertEqual(
            sum(g["summary"]["total_planned"] for g in groups), whole["total_planned"]
        )
        self.assertEqual(sum(len(g["items"]) for g in groups), len(items))

    def test_future_work_is_not_counted_as_unfinished(self):
        """A team is not behind on work whose date has not arrived."""
        self._activity(
            owner=self.james,
            school=self.school_a,
            planned=date.today() + timedelta(days=30),
        )

        summary = svc.summarize(svc.build_items(self.pl_user, fy=self.fy))

        self.assertEqual(summary["due_count"], 0)
        self.assertIsNone(summary["execution_progress"])


class CountryDirectorScopeTest(OversightFixture):
    def test_the_country_director_sees_every_team(self):
        self._activity(owner=self.james, school=self.school_a)
        self._activity(owner=self.rival_cceo, school=self.school_r)

        items = svc.build_items(self.cd_user, fy=self.fy)

        self.assertEqual(len(items), 2)

    def test_the_country_view_groups_by_program_lead(self):
        self._activity(owner=self.james, school=self.school_a, cost=10_000)
        self._activity(owner=self.mary, school=self.school_b, cost=15_000)
        self._activity(owner=self.rival_cceo, school=self.school_r, cost=40_000)

        groups = svc.group_by_program_lead(svc.build_items(self.cd_user, fy=self.fy))

        by_name = {g["name"]: g for g in groups}
        self.assertEqual(by_name["Team Lead"]["summary"]["planned_budget"], 25_000)
        self.assertEqual(by_name["Other Lead"]["summary"]["planned_budget"], 40_000)

    def test_the_country_summary_equals_its_expanded_detail(self):
        self._activity(owner=self.james, school=self.school_a, cost=10_000)
        self._activity(owner=self.rival_cceo, school=self.school_r, cost=40_000)
        self._assignment(school=self.school_b, managing_staff=self.mary)

        items = svc.build_items(self.cd_user, fy=self.fy)
        country = svc.summarize(items)
        groups = svc.group_by_program_lead(items)

        self.assertEqual(
            sum(g["summary"]["total_planned"] for g in groups),
            country["total_planned"],
            "count difference between summary and detail must be 0",
        )
        self.assertEqual(
            sum(g["summary"]["planned_budget"] for g in groups),
            country["planned_budget"],
            "budget difference between summary and detail must be UGX 0",
        )


class QueryBudgetTest(OversightFixture):
    def test_the_page_does_not_query_once_per_row(self):
        """A country page must cost a fixed number of statements, not one per
        activity — the difference between a page and a timeout."""
        for index in range(12):
            owner = self.james if index % 2 else self.mary
            self._activity(owner=owner, school=self.school_a, cost=1_000 * index)
        for _ in range(6):
            self._assignment(school=self.school_b, managing_staff=self.mary)

        # Five statements, and five whatever the row count: activities,
        # assignments, the staff directory, the supervisor links, the cost
        # lines. The summaries and groupings add none because they are folds
        # over the rows already in memory.
        with self.assertNumQueries(5):
            items = svc.build_items(self.cd_user, fy=self.fy)
            svc.summarize(items)
            svc.group_by_program_lead(items)

        self.assertEqual(len(items), 18)

    def test_the_query_count_does_not_grow_with_the_number_of_rows(self):
        """The property that matters: fixed cost, not merely a low number."""
        self._activity(owner=self.james, school=self.school_a, cost=1_000)

        with self.assertNumQueries(5):
            svc.build_items(self.cd_user, fy=self.fy)

        for index in range(40):
            self._activity(owner=self.mary, school=self.school_b, cost=index)

        with self.assertNumQueries(5):
            items = svc.build_items(self.cd_user, fy=self.fy)

        self.assertEqual(len(items), 41)
