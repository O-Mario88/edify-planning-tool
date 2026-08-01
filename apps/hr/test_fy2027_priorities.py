from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.activity_catalogue.services import apply_catalogue_snapshot
from apps.core.navigation import build_sidebar_for_user

from .milestone_progress import record_activity_progress
from .milestone_allocations import (
    approve_allocation,
    create_allocation,
    personal_milestone_targets,
    strategic_priority_overview,
    team_milestone_targets,
)
from .models import (
    MilestoneAllocation,
    MilestoneProgressCredit,
    PerformanceReview,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
)
from .priority_seeding import seed_fy2027_priorities


class Fy2027PrioritySeedTests(TestCase):
    def test_priority_overview_keeps_all_five_groups_visible_before_allocation(self):
        rows = strategic_priority_overview(fy="2027", staff_ids=[])

        self.assertEqual(
            [row["code"] for row in rows],
            [
                "PROGRAM_GROWTH_AND_EXPANSION",
                "PROGRAM_QUALITY",
                "BUSINESS_TRANSFORMATION",
                "EDUCATION_TECHNOLOGY",
                "GOVERNANCE_AND_PEOPLE_MANAGEMENT",
            ],
        )
        self.assertTrue(all(row["status"] == "Definition in progress" for row in rows))
        self.assertTrue(all(row["allocatedCount"] == 0 for row in rows))

    def test_seed_preserves_five_groups_order_and_source(self):
        seed_fy2027_priorities(actor_id="test")
        seed_fy2027_priorities(actor_id="test")
        priorities = list(
            StrategicPriority.objects.filter(fy="2027").order_by("sequence")
        )
        self.assertEqual(len(priorities), 5)
        self.assertEqual(
            [priority.code for priority in priorities],
            [
                "PROGRAM_GROWTH_AND_EXPANSION",
                "PROGRAM_QUALITY",
                "BUSINESS_TRANSFORMATION",
                "EDUCATION_TECHNOLOGY",
                "GOVERNANCE_AND_PEOPLE_MANAGEMENT",
            ],
        )
        dc = PriorityMilestone.objects.get(code="SCHOOLS_WITH_DCS")
        self.assertEqual(dc.source_text, "Schools with DCs — 255")
        self.assertEqual(dc.target_value, 255)
        self.assertTrue(dc.requires_definition)
        self.assertFalse(dc.active)

        cycle = StrategicPriorityCycle.objects.get(financial_year="2027")
        self.assertEqual(cycle.priorities.count(), 5)
        self.assertEqual(
            PriorityMilestone.objects.filter(priority__cycle=cycle).count(),
            68,
        )
        self.assertTrue(
            all(
                priority.source_document
                == "2027 priorities to be set by RVP.docx"
                for priority in priorities
            )
        )

    def test_dashboard_opens_the_newest_governed_cycle_without_a_year_query(self):
        seed_fy2027_priorities(actor_id="test")
        rvp = User.objects.create_user(
            email="rvp-priority-dashboard@example.test",
            name="RVP Priority Dashboard",
            roles=["RegionalVicePresident"],
            active_role="RegionalVicePresident",
            password="test-password",
            is_active=True,
        )
        self.client.force_login(rvp)

        response = self.client.get("/strategic-priorities")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["fy"], "2027")
        self.assertEqual(response.context["milestone_count"], 68)
        self.assertEqual(len(response.context["group_rows"]), 5)
        self.assertContains(response, "Priority Setting Dashboard")
        self.assertContains(response, "Program Growth and Expansion")
        self.assertContains(response, "Governance and People Management")

    def test_rvp_priority_setting_navigation_opens_the_governed_dashboard(self):
        rvp = User.objects.create_user(
            email="rvp-priority-navigation@example.test",
            name="RVP Priority Navigation",
            roles=["RegionalVicePresident"],
            active_role="RegionalVicePresident",
            password="test-password",
            is_active=True,
        )

        items = [
            item
            for section in build_sidebar_for_user(rvp, "/strategic-priorities")
            for item in section["items"]
        ]
        priority_setting = next(
            item for item in items if item["label"] == "Priority Setting"
        )
        personal = next(
            item for item in items if item["label"] == "My Performance Agreement"
        )

        self.assertEqual(priority_setting["url"], "/strategic-priorities")
        self.assertTrue(priority_setting["active"])
        self.assertEqual(personal["url"], "/my-performance")
        self.assertFalse(personal["active"])
        self.assertEqual(
            sum(item["url"] == "/strategic-priorities" for item in items),
            1,
        )

    def test_undefined_milestones_do_not_populate_targets(self):
        milestone = PriorityMilestone.objects.get(code="IDE")
        self.assertTrue(milestone.requires_definition)
        self.assertFalse(milestone.active)
        self.assertFalse(
            MilestoneAllocation.objects.filter(milestone=milestone).exists()
        )
        self.assertFalse(milestone.period_targets.exists())


class MilestoneCreditDeduplicationTests(TestCase):
    def test_one_underlying_activity_creates_one_credit_per_rule(self):
        milestone = PriorityMilestone.objects.get(code="CLA")
        milestone.requires_definition = False
        milestone.definition_status = "approved"
        milestone.metric_definition = PriorityMilestone.objects.get(
            code="NEW_SCHOOLS"
        ).metric_definition
        milestone.target_value = 1
        milestone.target_unit = "Schools"
        milestone.due_date = date(2027, 9, 30)
        milestone.active = True
        milestone.save()
        item = ActivityCatalogueItem.objects.get(
            stable_code="CLA_CHARACTER_DEVELOPMENT"
        )
        activity = Activity.objects.create(
            activity_type=item.workflow_kind,
            status="ia_verified",
            planned_date=date(2027, 1, 10),
            fy="2027",
            focus_intervention="christlike_behaviour",
        )
        apply_catalogue_snapshot(
            activity,
            item=item,
            requested_intervention="christlike_behaviour",
        )

        self.assertEqual(record_activity_progress(activity), 1)
        self.assertEqual(record_activity_progress(activity), 0)
        self.assertEqual(
            MilestoneProgressCredit.objects.filter(activity=activity).count(),
            1,
        )


class MilestoneAllocationProjectionTests(TestCase):
    def test_approved_allocation_populates_my_team_and_performance_snapshot(self):
        user = User.objects.create_user(
            email="milestone-target@example.test",
            name="Milestone Owner",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
        )
        staff = StaffProfile.objects.create(
            user=user,
            title="CCEO",
            country="Uganda",
        )
        milestone = PriorityMilestone.objects.get(code="NEW_SCHOOLS")
        milestone.requires_definition = False
        milestone.definition_status = "approved"
        milestone.active = True
        milestone.save(
            update_fields=[
                "requires_definition",
                "definition_status",
                "active",
                "updated_at",
            ]
        )
        allocation = create_allocation(
            milestone=milestone,
            data={
                "allocatedToType": "employee",
                "employeeId": staff.id,
                "allocatedTarget": "100.01",
                "weight": "20",
                "effectiveDate": "2026-10-01",
                "allocationReason": "Approved FY2027 country cascade.",
            },
            principal=user,
        )
        approve_allocation(allocation, principal=user)
        allocation.refresh_from_db()
        periods = list(allocation.period_targets.order_by("period_start"))
        self.assertEqual(len(periods), 12)
        self.assertEqual(
            sum((period.planned_value for period in periods), 0),
            allocation.allocated_target,
        )

        personal = personal_milestone_targets(staff=staff, fy="2027", month_of_fy=1)
        self.assertEqual(len(personal), 1)
        self.assertEqual(personal[0]["fyPlan"], allocation.allocated_target)
        self.assertEqual(personal[0]["allocatedTarget"], allocation.allocated_target)
        self.assertEqual(personal[0]["targetSource"], "Approved Milestone Allocation")
        self.assertEqual(personal[0]["linkedActivities"], 0)
        overview = strategic_priority_overview(
            fy="2027",
            staff_ids=[staff.id],
        )
        growth = next(
            row for row in overview if row["code"] == "PROGRAM_GROWTH_AND_EXPANSION"
        )
        self.assertEqual(growth["allocatedCount"], 1)
        self.assertEqual(growth["status"], "Allocated")
        team = team_milestone_targets(users=[user], fy="2027", month_of_fy=1)
        self.assertEqual(team[0]["teamMember"], user.name)
        self.assertEqual(team[0]["risk"], "Needs attention")
        review = PerformanceReview.objects.create(
            staff=staff,
            period="FY2027",
            fy="2027",
            due_date=date(2027, 9, 30),
        )
        from .performance_engine import take_snapshot

        snapshot = take_snapshot(review, "mid_year")
        self.assertEqual(
            snapshot.data["strategicMilestones"][0]["allocationId"],
            allocation.id,
        )
