from datetime import date, datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.hr.fiscal_year_rollover import rollover_fiscal_year
from apps.hr.models import (
    FiscalYearRollover,
    PerformanceCycle,
    PerformancePriority,
    PerformanceReview,
    StrategicPriority,
    StrategicPriorityLevel,
    StrategicPriorityRoleRule,
    StrategicPriorityStatus,
)
from apps.schools.models import School
from apps.ssa.models import SsaRecord
from apps.targets.models import (
    MostSignificantChangeStory,
    TargetAchievementLedger,
    TargetArea,
)
from apps.targets.my_targets import MyTargetQueryService, active_target_areas


class FiscalYearRolloverTests(TestCase):
    OLD_FY = "2030"
    NEW_FY = "2031"

    def setUp(self):
        active_target_areas()
        self.user = User.objects.create_user(
            email="rollover-cceo@example.test",
            name="Rollover CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
            status="active",
        )
        self.staff = StaffProfile.objects.create(
            user=self.user,
            title="CCEO",
            onboarding_state="active",
        )
        self.old_cycle = PerformanceCycle.objects.create(fy=self.OLD_FY)
        self.old_review = PerformanceReview.objects.create(
            staff=self.staff,
            period=f"FY{self.OLD_FY}",
            fy=self.OLD_FY,
            due_date=date(2030, 9, 30),
            stage="priorities_agreed",
        )
        PerformancePriority.objects.create(
            review=self.old_review,
            sequence=1,
            outcome_statement="Publish approved change stories",
            metric_key="mscs",
            target_number=2,
            target="2 approved stories",
            weight=100,
        )
        self.old_activity = Activity.objects.create(
            activity_type="school_visit",
            status="ia_verified",
            fy=self.OLD_FY,
            quarter="Q4",
            planned_date=date(2030, 9, 15),
            responsible_staff_id=self.staff.id,
        )
        self.school = School.objects.create(
            school_id="ROLLOVER-SCHOOL",
            name="Rollover School",
            current_fy_ssa_status="done",
            planning_readiness="ready_for_support_planning",
        )
        self.old_ssa = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=timezone.make_aware(datetime(2030, 9, 10, 9, 0)),
            fy=self.OLD_FY,
            quarter="Q4",
            verification_status="confirmed",
            uploaded_by=self.user.id,
        )
        mscs_area = TargetArea.objects.get(key="mscs")
        TargetAchievementLedger.objects.create(
            user_id=self.user.id,
            area=mscs_area,
            source_type="mscs",
            source_id="historic-story",
            activity_date=date(2030, 9, 20),
            fy=self.OLD_FY,
            credited_month=12,
            credited_quarter="Q4",
            quantity=1,
            validation_status="validated",
        )

        priority = StrategicPriority.objects.create(
            fy=self.NEW_FY,
            level=StrategicPriorityLevel.REGIONAL,
            title="Document school transformation",
            strategic_purpose="Make verified school progress visible.",
            status=StrategicPriorityStatus.PUBLISHED,
            weight_min=5,
            weight_max=30,
        )
        StrategicPriorityRoleRule.objects.create(
            priority=priority,
            role="CCEO",
            accountability="execute",
            metric_key="mscs",
            outcome_statement="Publish approved school change stories",
            target_guidance="Agree the annual MSCS target with your manager",
            default_weight=20,
        )

    def _roll(self):
        return rollover_fiscal_year(
            fy=self.NEW_FY,
            as_of=date(2030, 10, 1),
            initiated_by="test",
        )

    def test_october_first_opens_fresh_priority_driven_year_and_keeps_history(self):
        report = self._roll()

        self.old_cycle.refresh_from_db()
        self.assertEqual(self.old_cycle.status, "closed")
        self.assertTrue(self.old_review.snapshots.filter(window="year_end").exists())
        self.assertTrue(Activity.objects.filter(pk=self.old_activity.pk).exists())
        self.assertTrue(SsaRecord.objects.filter(pk=self.old_ssa.pk).exists())
        self.school.refresh_from_db()
        self.assertEqual(self.school.current_fy_ssa_status, "not_done")
        self.assertEqual(self.school.planning_readiness, "requires_cluster")
        self.assertEqual(
            TargetAchievementLedger.objects.filter(fy=self.OLD_FY).count(), 1
        )

        new_cycle = PerformanceCycle.objects.get(fy=self.NEW_FY)
        self.assertEqual(new_cycle.active_window, "priority_setting")
        self.assertEqual(new_cycle.window_deadline, date(2030, 10, 31))
        review = PerformanceReview.objects.get(staff=self.staff, fy=self.NEW_FY)
        self.assertEqual(review.stage, "priorities_draft")
        self.assertEqual(
            list(review.priorities.values_list("metric_key", flat=True)), ["mscs"]
        )
        self.assertEqual(
            report["prioritySource"],
            "user_set_strategic_priorities_and_agreements",
        )
        self.assertEqual(report["currentVerifiedActivities"], 0)
        self.assertEqual(report["currentValidatedCredits"], 0)
        self.assertEqual(report["schoolsResetToSsaRequired"], 1)
        self.assertEqual(
            MyTargetQueryService.monthly_achievements(
                self.user,
                self.NEW_FY,
                areas=[],
            ),
            {},
        )

    def test_rerun_is_read_only_and_does_not_duplicate_drafts_or_notifications(self):
        first = self._roll()
        second = self._roll()

        self.assertFalse(first["alreadyCompleted"])
        self.assertTrue(second["alreadyCompleted"])
        self.assertEqual(FiscalYearRollover.objects.filter(fy=self.NEW_FY).count(), 1)
        self.assertEqual(
            PerformanceReview.objects.filter(staff=self.staff, fy=self.NEW_FY).count(),
            1,
        )

    def test_dry_run_rolls_back_every_change(self):
        report = rollover_fiscal_year(
            fy=self.NEW_FY,
            as_of=date(2030, 10, 1),
            initiated_by="test",
            dry_run=True,
        )

        self.assertTrue(report["dryRun"])
        self.assertFalse(FiscalYearRollover.objects.filter(fy=self.NEW_FY).exists())
        self.old_cycle.refresh_from_db()
        self.assertEqual(self.old_cycle.status, "open")


class MscsPriorityMetricTests(TestCase):
    def test_mscs_priority_drives_personal_targets_and_only_approved_stories_count(
        self,
    ):
        active_target_areas()
        user = User.objects.create_user(
            email="mscs-priority@example.test",
            name="MSCS Owner",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
            status="active",
        )
        staff = StaffProfile.objects.create(user=user, title="CCEO")
        review = PerformanceReview.objects.create(
            staff=staff,
            period="FY2031",
            fy="2031",
            due_date=date(2031, 9, 30),
            stage="priorities_agreed",
        )
        PerformancePriority.objects.create(
            review=review,
            sequence=1,
            outcome_statement="Publish school change stories",
            metric_key="mscs",
            target_number=2,
            target="2 approved stories",
            weight=100,
        )
        story = MostSignificantChangeStory.objects.create(
            user_id=user.id,
            title="A school changed",
            narrative="Verified change evidence.",
            story_date=date(2030, 10, 15),
            status="submitted",
        )

        areas = MyTargetQueryService.get_page(user, fy="2031", month_of_fy=1)[
            "area_cards"
        ]
        self.assertEqual(
            [(row["key"], row["achieved"]) for row in areas], [("mscs", 0)]
        )

        story.status = "approved"
        story.save(update_fields=["status", "updated_at"])
        areas = MyTargetQueryService.get_page(user, fy="2031", month_of_fy=1)[
            "area_cards"
        ]
        self.assertEqual(
            [(row["key"], row["achieved"]) for row in areas], [("mscs", 1)]
        )
