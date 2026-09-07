"""A milestone's progress comes from the plan (owner, 2026-09-07).

"The priorities should be linked to the plan. When the users plan and
complete, the progress bar and percentage should show clearly since everything
will be planned including the non school activities."

Until now a milestone reported progress only through approved allocations and
their period rows — nothing for an undistributed milestone, and movement only
on Impact Assessment's verification. milestone_plan_progress() reads the
activities that match a milestone's rules directly: planned, completed and
verified, against the milestone's own target, in the unit its counting basis
names. A cluster meeting with no school counts like anything else.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.core.rbac import EdifyRole
from apps.hr.models import (
    MilestoneActivityRule,
    MilestoneMetricDefinition,
    MilestoneProgressCredit,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
)
from apps.hr.target_distribution import milestone_plan_progress
from apps.schools.models import School


def _milestone(cycle, priority, *, code, title, target, measurement="count"):
    metric = MilestoneMetricDefinition.objects.create(
        metric_key=f"plan_{code.lower()}", canonical_label=title
    )
    return PriorityMilestone.objects.create(
        priority=priority,
        metric_definition=metric,
        code=code,
        title=title,
        source_text=title,
        milestone_type="output",
        measurement_type=measurement,
        progress_source="activities",
        target_value=Decimal(target),
        requires_definition=False,
        # An active milestone must be defined — the constraint that keeps an
        # undefined source row from ever earning credit.
        definition_status="approved",
        active=True,
    )


class MilestonePlanProgressTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cycle = StrategicPriorityCycle.objects.create(
            financial_year="2026", title="FY2026", scope_type="country", country_id="Uganda"
        )
        cls.priority = StrategicPriority.objects.create(
            cycle=cls.cycle, fy="2026", level="country", country_id="Uganda",
            title="Program Quality", sequence=1,
        )
        cls.visit_item = ActivityCatalogueItem.objects.create(
            stable_code="PLAN-VISIT", source_name="School visit", display_name="School visit",
            activity_type="school_visit", delivery_method="school_visit",
            workflow_kind="school_visit", status="active",
            # An active item must be costable and evidenced.
            costing_profile="SCHOOL_VISIT", evidence_profile="VISIT_REPORT",
            salesforce_record_type="SCHOOL_VISIT",
        )
        cls.meeting_item = ActivityCatalogueItem.objects.create(
            stable_code="PLAN-MEET", source_name="Cluster meeting", display_name="Cluster meeting",
            activity_type="cluster_meeting", delivery_method="cluster_meeting",
            workflow_kind="cluster_meeting", status="active",
            costing_profile="CLUSTER_MEETING", evidence_profile="MEETING_MINUTES",
            salesforce_record_type="CLUSTER_MEETING",
        )
        cls.schools_ms = _milestone(
            cls.cycle, cls.priority, code="M-SCHOOLS", title="Schools supported", target="10"
        )
        MilestoneActivityRule.objects.create(
            milestone=cls.schools_ms, catalogue_item=cls.visit_item,
            counting_basis="UNIQUE_SCHOOLS_SUPPORTED",
        )
        cls.meetings_ms = _milestone(
            cls.cycle, cls.priority, code="M-MEET", title="Cluster meetings held", target="4"
        )
        MilestoneActivityRule.objects.create(
            milestone=cls.meetings_ms, catalogue_item=cls.meeting_item,
            counting_basis="ACTIVITIES_COMPLETED",
        )
        cls.unlinked_ms = _milestone(
            cls.cycle, cls.priority, code="M-NONE", title="No rule yet", target="5"
        )
        cls.a = School.objects.create(name="Plan School A", school_id="PLAN-A")
        cls.b = School.objects.create(name="Plan School B", school_id="PLAN-B")

    def _visit(self, school, status, fy="2026"):
        return Activity.objects.create(
            activity_type="school_visit", status=status, school=school,
            catalogue_item=self.visit_item, fy=fy,
        )

    def test_planned_and_completed_count_distinct_schools_against_the_target(self):
        self._visit(self.a, "scheduled")
        self._visit(self.a, "completed")          # same school, done
        self._visit(self.b, "planned")
        self._visit(self.b, "cancelled")          # neither planned nor done

        out = milestone_plan_progress([self.schools_ms, self.meetings_ms, self.unlinked_ms])
        row = out[self.schools_ms.id]
        self.assertEqual(row["unit"], "schools")
        # A and B are planned; A is completed. Distinct schools, not visits.
        self.assertEqual(row["planned"], 2)
        self.assertEqual(row["completed"], 1)
        self.assertEqual(row["target"], Decimal("10"))
        self.assertEqual(row["pct"], 10.0)
        self.assertEqual(row["planned_pct"], 20.0)
        self.assertIsNotNone(row["classification"])

    def test_a_cluster_meeting_with_no_school_counts(self):
        """Non-school work is in the plan too."""
        Activity.objects.create(
            activity_type="cluster_meeting", status="completed",
            catalogue_item=self.meeting_item, fy="2026",
        )
        Activity.objects.create(
            activity_type="cluster_meeting", status="scheduled",
            catalogue_item=self.meeting_item, fy="2026",
        )
        row = milestone_plan_progress([self.meetings_ms])[self.meetings_ms.id]
        self.assertEqual(row["unit"], "activities")
        self.assertEqual((row["planned"], row["completed"]), (1, 1))
        self.assertEqual(row["pct"], 25.0)

    def test_participant_milestones_count_people_not_activity_rows(self):
        teachers = _milestone(
            self.cycle,
            self.priority,
            code="M-TEACHERS",
            title="Teachers trained",
            target="20",
        )
        MilestoneActivityRule.objects.create(
            milestone=teachers,
            catalogue_item=self.meeting_item,
            counting_basis="TEACHERS_TRAINED",
        )
        Activity.objects.create(
            activity_type="cluster_meeting",
            status="scheduled",
            catalogue_item=self.meeting_item,
            fy="2026",
            expected_participants=8,
        )
        Activity.objects.create(
            activity_type="cluster_meeting",
            status="completed",
            catalogue_item=self.meeting_item,
            fy="2026",
            teachers_attended=5,
        )

        row = milestone_plan_progress([teachers])[teachers.id]
        self.assertEqual(row["unit"], "teachers")
        self.assertEqual((row["planned"], row["completed"]), (8, 5))
        self.assertEqual(row["pct"], 25.0)

    def test_verified_credits_ride_along(self):
        done = self._visit(self.a, "ia_verified")
        rule = self.schools_ms.activity_rules.first()
        from django.utils import timezone

        MilestoneProgressCredit.objects.create(
            rule=rule, activity=done, credited_value=Decimal("1"), credited_at=timezone.now()
        )
        row = milestone_plan_progress([self.schools_ms])[self.schools_ms.id]
        self.assertEqual(row["verified"], Decimal("1"))
        self.assertEqual(row["completed"], 1)

    def test_a_milestone_with_no_rule_has_no_entry(self):
        """No plan to link to is reported as absence, not as 0%."""
        out = milestone_plan_progress([self.unlinked_ms])
        self.assertNotIn(self.unlinked_ms.id, out)

    def test_another_year_does_not_count(self):
        self._visit(self.a, "completed", fy="2025")
        row = milestone_plan_progress([self.schools_ms], fy="2026").get(self.schools_ms.id)
        self.assertEqual(row["completed"], 0)

    def test_the_priority_setting_page_draws_a_meter_per_row(self):
        self._visit(self.a, "completed")
        User = get_user_model()
        cd = User.objects.create_user(
            email="meter-cd@edify.test", name="Meter CD",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value, password="StrongPassphrase!23",
        )
        self.client.force_login(cd)
        response = self.client.get("/strategic-priorities?fy=2026")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(">Progress<", html)
        # Each milestone draws its meter twice — in the summary row, and again
        # with its words in the detail beneath it. Two linked, one not.
        self.assertEqual(html.count('class="edify-meter"'), 4)
        self.assertEqual(html.count("edify-meter--unlinked"), 2)
        self.assertIn("10% complete", html)
        self.assertIn("1 done · 0 planned · of 10 schools", html)


class LinkMilestonesToPlanTest(TestCase):
    """Add activity rules to the milestones so the bars actually fill (owner,
    2026-09-07). Two halves: the shape-of-work milestones get rules on the
    catalogue's standard items, and historical activities get the catalogue
    link the drawer would have stamped at creation."""

    @classmethod
    def setUpTestData(cls):
        from apps.hr.priority_seeding import seed_fy2027_priorities

        seed_fy2027_priorities(actor_id="test")

    def _rules(self, code):
        from apps.hr.models import MilestoneActivityRule

        return list(
            MilestoneActivityRule.objects.filter(milestone__code=code, active=True)
            .select_related("catalogue_item")
            .order_by("catalogue_item__stable_code")
        )

    def test_shape_of_work_milestones_get_rules_on_the_standard_items(self):
        visits = self._rules("SCHOOL_VISITS")
        self.assertIn("STANDARD_SCHOOL_VISIT", [r.catalogue_item.stable_code for r in visits])
        self.assertTrue(all(r.counting_basis == "ACTIVITIES_DELIVERED" for r in visits))
        # No intervention gate: a visit counts whatever focus its planner named.
        self.assertTrue(all(r.target_intervention == "" for r in visits))

        core_ssa = self._rules("CORE_SSA_COVERAGE")
        self.assertTrue(core_ssa)
        self.assertTrue(all(r.school_type == "core" for r in core_ssa))
        self.assertTrue(all(r.counting_basis == "UNIQUE_SCHOOLS_SUPPORTED" for r in core_ssa))

        clusters = self._rules("CLUSTER_COVERAGE")
        self.assertEqual(
            [r.catalogue_item.stable_code for r in clusters],
            ["STANDARD_CLUSTER_MEETING", "STANDARD_CLUSTER_TRAINING"],
        )
        # The curriculum milestones keep their intervention gate.
        cla = self._rules("CLA")
        self.assertEqual(cla[0].target_intervention, "christlike_behaviour")
        # Not activity-shaped: nothing in the plan IS a new school.
        self.assertEqual(self._rules("NEW_SCHOOLS"), [])

    def test_the_seeder_is_idempotent_about_rules(self):
        from apps.hr.models import MilestoneActivityRule
        from apps.hr.priority_seeding import seed_fy2027_priorities

        before = MilestoneActivityRule.objects.count()
        seed_fy2027_priorities(actor_id="test")
        self.assertEqual(MilestoneActivityRule.objects.count(), before)

    def _activities(self):
        school = School.objects.create(name="Link School", school_id="LINK-1")
        visit = Activity.objects.create(
            activity_type="school_visit", status="completed", school=school, fy="2027",
            planned_date=timezone.localdate(),
        )
        meeting = Activity.objects.create(
            activity_type="cluster_meeting", status="scheduled", fy="2027",
            planned_date=timezone.localdate(),
        )
        ssa = Activity.objects.create(
            activity_type="ssa_activity", status="completed", school=school, fy="2027",
            planned_date=timezone.localdate(),
        )
        # "training" has five governed titles and no standard one: ambiguous,
        # and the resolver refuses to guess.
        training = Activity.objects.create(
            activity_type="training", status="completed", school=school, fy="2027",
            planned_date=timezone.localdate(),
        )
        return school, visit, meeting, ssa, training

    def test_history_is_linked_the_way_the_drawer_would_link_it(self):
        from apps.hr.management.commands.link_milestones_to_plan import (
            link_activities_to_catalogue,
        )

        school, visit, meeting, ssa, training = self._activities()
        report = link_activities_to_catalogue()
        self.assertEqual(report["linkedTotal"], 3)
        self.assertEqual(report["skippedTotal"], 1)
        for activity, code in (
            (visit, "STANDARD_SCHOOL_VISIT"),
            (meeting, "STANDARD_CLUSTER_MEETING"),
            (ssa, "STANDARD_SCHOOL_VISIT_SSA_COLLECTION"),
        ):
            activity.refresh_from_db()
            self.assertEqual(activity.catalogue_item.stable_code, code)
            # Stamped through the same service the drawer uses.
            self.assertEqual(activity.delivery_method_snapshot, activity.catalogue_item.delivery_method)
            self.assertIsNotNone(activity.catalogue_version)
        training.refresh_from_db()
        self.assertIsNone(training.catalogue_item)
        # Second run: nothing left to link.
        self.assertEqual(link_activities_to_catalogue()["linkedTotal"], 0)

    def test_a_partner_activity_takes_the_item_its_assignment_named(self):
        from apps.hr.management.commands.link_milestones_to_plan import (
            link_activities_to_catalogue,
        )
        from apps.partners.models import Partner, PartnerAssignment

        school = School.objects.create(name="Partner School", school_id="LINK-P")
        partner = Partner.objects.create(name="Link Partner", active_status=True)
        item = ActivityCatalogueItem.objects.get(stable_code="STANDARD_SCHOOL_VISIT_SSA_COLLECTION")
        activity = Activity.objects.create(
            activity_type="partner_activity", status="completed", school=school, fy="2027",
            planned_date=timezone.localdate(), delivery_type="partner",
        )
        PartnerAssignment.objects.create(
            school=school, partner=partner, catalogue_item=item, scheduled_activity=activity,
            status="scheduled",
        )
        link_activities_to_catalogue()
        activity.refresh_from_db()
        self.assertEqual(activity.catalogue_item_id, item.id)

    def test_a_dry_run_writes_nothing(self):
        from apps.hr.management.commands.link_milestones_to_plan import (
            link_activities_to_catalogue,
        )

        _, visit, *_ = self._activities()
        report = link_activities_to_catalogue(dry_run=True)
        self.assertEqual(report["linkedTotal"], 3)
        visit.refresh_from_db()
        self.assertIsNone(visit.catalogue_item)

    def test_linked_history_moves_the_bar(self):
        from apps.hr.management.commands.link_milestones_to_plan import (
            link_activities_to_catalogue,
        )
        from apps.hr.models import PriorityMilestone
        from apps.hr.target_distribution import milestone_plan_progress

        self._activities()
        link_activities_to_catalogue()
        visits = PriorityMilestone.objects.get(code="SCHOOL_VISITS")
        row = milestone_plan_progress([visits], fy="2027")[visits.id]
        # The visit and the SSA visit both count as school visits; the cluster
        # meeting does not. No target yet, so no percentage — but real counts.
        self.assertEqual((row["completed"], row["planned"]), (2, 0))
        self.assertIsNone(row["pct"])
        clusters = PriorityMilestone.objects.get(code="CLUSTER_COVERAGE")
        self.assertEqual(milestone_plan_progress([clusters], fy="2027")[clusters.id]["planned"], 1)

    def test_the_meter_shows_counts_until_a_target_exists(self):
        from django.template.loader import render_to_string

        html = render_to_string(
            "components/meter.html",
            {"progress": {"unit": "activities", "target": None, "planned": 3, "completed": 148,
                          "verified": 0, "pct": None, "planned_pct": None, "classification": None},
             "meta": True},
        )
        self.assertIn("148 done · 3 planned</span>", html)
        self.assertIn("no target yet — define the metric to get a percentage", html)
