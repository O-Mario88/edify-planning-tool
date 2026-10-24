"""The target engine counts every milestone of a scope in one read (2026-10-24).

My Targets took two seconds and a Programme Lead's To-Do queue seven and a
half on a seeded database: `_allocation_priorities` asked one counting query
per milestone, per period (844 for one Lead). The counts are now read for all
of a scope's milestones together, grouped by milestone — and must be exactly
what the one-by-one reading gave: distinct schools for a school basis, the
largest figure per activity summed for an attendance or credited basis, and
no figure at all (not zero) where a sum has nothing to add.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.hr import target_distribution as distribution
from apps.hr.accountability import allocation_priorities
from apps.hr.milestone_progress import (
    _aggregate_credits,
    aggregate_credits_by_milestone,
)
from apps.hr.models import MilestoneActivityRule, MilestoneProgressCredit
from apps.hr.test_target_distribution import FY, DistributionFixture
from apps.schools.models import School

BASES = (
    "UNIQUE_SCHOOLS_SUPPORTED",
    "TEACHERS_TRAINED",
    "SCHOOL_LEADERS_TRAINED",
    "ACTIVITIES_COMPLETED",
)


class BatchedProgressTest(DistributionFixture):
    def rule(self, milestone, basis, item=None):
        return MilestoneActivityRule.objects.create(
            milestone=milestone,
            catalogue_item=item
            or ActivityCatalogueItem.objects.get(
                stable_code="CLA_CHARACTER_DEVELOPMENT"
            ),
            counting_basis=basis,
            minimum_completion_state="ia_verified",
            weight=1,
        )

    def activity(self, staff, *, school=None, teachers=None, leaders=None):
        return Activity.objects.create(
            activity_type="school_visit",
            status="ia_verified",
            planned_date=date(2026, 10, 5),
            fy=FY,
            responsible_staff_id=staff.id,
            delivery_type="staff",
            school=school,
            teachers_attended=teachers,
            leaders_attended=leaders,
        )

    def credit(self, rule, activity, value="1"):
        return MilestoneProgressCredit.objects.create(
            rule=rule,
            activity=activity,
            credited_value=Decimal(value),
            credited_at=timezone.now(),
        )

    def build(self):
        """Four milestones, one of each counting family, and credits that
        reach every edge: one school twice, two rules crediting one activity,
        an attendance figure that is missing, a school-less activity, and a
        reversed credit."""
        schools = [
            School.objects.create(school_id=f"BATCH-{n}", name=f"Batch {n}")
            for n in range(2)
        ]
        other_item = (
            ActivityCatalogueItem.objects.exclude(
                stable_code="CLA_CHARACTER_DEVELOPMENT"
            )
            .order_by("stable_code")
            .first()
        )
        milestones, rules = {}, {}
        for n, basis in enumerate(BASES):
            milestone = self._milestone(f"BATCH_{n}", target="10")
            milestones[basis] = milestone
            rules[basis] = (
                self.rule(milestone, basis),
                self.rule(milestone, basis, item=other_item),
            )
        a = self.activity(self.cceo_a_sp, school=schools[0], teachers=7, leaders=2)
        b = self.activity(self.cceo_a_sp, school=schools[0], teachers=3, leaders=None)
        c = self.activity(self.cceo_a_sp, school=schools[1], teachers=None, leaders=4)
        d = self.activity(self.cceo_a_sp, school=None, teachers=5, leaders=1)
        e = self.activity(self.cceo_a_sp, school=schools[1], teachers=9, leaders=9)
        for basis in BASES:
            first, second = rules[basis]
            for activity in (a, b, c, d):
                self.credit(first, activity, value="2")
            self.credit(second, a, value="3")
            # Reversed: never counted.
            gone = self.credit(second, e, value="9")
            MilestoneProgressCredit.objects.filter(pk=gone.pk).update(
                reversed_at=timezone.now()
            )
        return milestones

    def test_the_batch_gives_each_milestone_its_one_by_one_figure(self):
        milestones = self.build()
        empty = self._milestone("BATCH_EMPTY", target="10")
        self.rule(empty, "TEACHERS_TRAINED")
        empty_school = self._milestone("BATCH_EMPTY_SCHOOL", target="10")
        self.rule(empty_school, "UNIQUE_SCHOOLS_SUPPORTED")
        bases = {str(m.id): {basis} for basis, m in milestones.items()}
        bases[str(empty.id)] = {"TEACHERS_TRAINED"}
        bases[str(empty_school.id)] = {"UNIQUE_SCHOOLS_SUPPORTED"}
        credits = MilestoneProgressCredit.objects.filter(
            rule__active=True, reversed_at__isnull=True
        )

        batched = aggregate_credits_by_milestone(credits, bases)

        for milestone_id, basis in bases.items():
            with self.subTest(basis=basis, milestone=milestone_id):
                one = _aggregate_credits(
                    credits.filter(rule__milestone_id=milestone_id), basis
                )
                self.assertEqual(batched[milestone_id], one)
        # The edges the figures hang on.
        self.assertEqual(batched[str(milestones["UNIQUE_SCHOOLS_SUPPORTED"].id)], 2)
        self.assertEqual(batched[str(milestones["TEACHERS_TRAINED"].id)], 15)
        self.assertEqual(batched[str(milestones["SCHOOL_LEADERS_TRAINED"].id)], 7)
        self.assertEqual(
            batched[str(milestones["ACTIVITIES_COMPLETED"].id)], Decimal("9")
        )
        self.assertEqual(batched[str(empty_school.id)], 0)
        self.assertIsNone(batched[str(empty.id)])

    def test_a_scope_reads_its_counts_in_the_same_queries_however_many_milestones(
        self,
    ):
        def distribute(code):
            milestone = self._milestone(code, target="10")
            milestone.weight = 10
            milestone.save()
            self.rule(milestone, "ACTIVITIES_COMPLETED")
            team = self._team_allocation(milestone, self.pl_sp, 10)
            distribution.approve_team_distribution(milestone, principal=self.ia)
            team.refresh_from_db()
            self._employee_allocation(milestone, self.cceo_a_sp, 10, parent=team)
            distribution.approve_employee_distribution(team, principal=self.pl)

        def queries(**options):
            with CaptureQueriesContext(connection) as captured:
                allocation_priorities(self.cceo_a, FY, **options)
            return len(captured.captured_queries)

        distribute("BATCH_Q1")
        one = queries(include_plans=False)
        one_with_plans = queries()
        for code in ("BATCH_Q2", "BATCH_Q3", "BATCH_Q4"):
            distribute(code)
        self.assertEqual(len(allocation_priorities(self.cceo_a, FY)["rows"]), 4)
        self.assertEqual(queries(include_plans=False), one)
        self.assertEqual(queries(), one_with_plans)
