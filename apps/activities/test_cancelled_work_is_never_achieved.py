"""TGT-02: cancelling or deferring verified work must withdraw its credit.

The platform law is "planned work must never be shown as achieved work", and
its converse binds just as hard: work that has been called off is not achieved
work either. `ia_return` already reverses the milestone credit an activity
earned at ia_confirm (apps/activities/services.py), as do IA invalidation
(apps/activities/ia_services.py) and closure invalidation
(apps/activities/closure_services.py) — but `_cancel_or_defer` flipped the
status and synced the money while leaving the credit standing, so a cancelled
school visit kept counting toward a CCEO's verified achievement for ever.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities import services as asvc
from apps.activities.models import Activity
from apps.geography.models import District, Region
from apps.schools.models import School


class CancelledWorkLosesItsMilestoneCreditTest(TestCase):
    """TGT-02: the credit follows the work out of the achieved column."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="TGT02 Region")
        cls.district = District.objects.create(name="TGT02 District", region=cls.region)
        cls.school = School.objects.create(
            school_id="SCH-TGT02-1",
            name="TGT02 Primary",
            region=cls.region,
            district=cls.district,
        )

    def setUp(self):
        self.admin = User.objects.create(
            id="tgt02-admin",
            email="tgt02-admin@edify.org",
            name="TGT02 Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(
            id="tgt02-admin-sp", user=self.admin, title="Administrator"
        )

    def _verified_activity_with_credit(self, suffix: str):
        """Build a verified activity that has really earned milestone credit.

        Returns (activity, period). The caller asserts the credit exists before
        acting, because a fixture that never reaches the credit engine would
        make the "credit is gone" assertion pass for the wrong reason.
        """
        from apps.activity_catalogue.models import ActivityCatalogueItem
        from apps.hr.milestone_progress import record_activity_progress
        from apps.hr.models import (
            MilestoneActivityRule,
            MilestoneAllocation,
            MilestoneDefinitionStatus,
            MilestoneMetricDefinition,
            MilestonePeriodTarget,
            PriorityMilestone,
            StrategicPriority,
            StrategicPriorityCycle,
        )

        # The reference-data receiver already publishes the live cycles, so
        # reuse rather than collide with the unique financial_year.
        cycle, _ = StrategicPriorityCycle.objects.get_or_create(
            financial_year="2027",
            defaults={"title": "TGT02 cycle", "country_id": "Uganda"},
        )
        priority = StrategicPriority.objects.create(
            cycle=cycle,
            fy="2027",
            level="country",
            title=f"TGT02 cancellation guard {suffix}",
            strategic_purpose="Prove cancelled work stops counting as achieved",
            country_id="Uganda",
        )
        # A DB constraint (active_milestone_must_be_defined) requires an
        # active milestone to carry an approved metric definition.
        definition = MilestoneMetricDefinition.objects.create(
            metric_key=f"tgt02_schools_supported_{suffix}",
            canonical_label="TGT02 schools supported",
        )
        milestone = PriorityMilestone.objects.create(
            priority=priority,
            metric_definition=definition,
            definition_status=MilestoneDefinitionStatus.APPROVED,
            requires_definition=False,
            code=f"TGT02_MILESTONE_{suffix.upper()}",
            title="Schools supported",
            source_text="TGT02 fixture",
            milestone_type="output",
            measurement_type="count",
            progress_source="activity",
            target_value=100,
            target_unit="schools",
            # active defaults to False; the credit engine filters on
            # milestone__active=True, so without this the fixture would never
            # reach the code under test.
            active=True,
        )
        item = ActivityCatalogueItem.objects.create(
            stable_code=f"TGT02_ITEM_{suffix.upper()}",
            source_name="TGT02 item",
            display_name="TGT02 item",
            activity_type="school_visit",
            delivery_method="school_visit",
            workflow_kind="school_visit",
            status="active",
            salesforce_record_type="VISIT",
            salesforce_expected_prefix="VS-",
            evidence_profile="SCHOOL_VISIT_FORM",
            costing_profile="STAFF_SCHOOL_VISIT",
        )
        MilestoneActivityRule.objects.create(
            milestone=milestone,
            catalogue_item=item,
            counting_basis="UNIQUE_SCHOOLS_SUPPORTED",
        )
        holder = User.objects.create(
            id=f"tgt02-cceo-{suffix}",
            email=f"tgt02-cceo-{suffix}@edify.org",
            name="TGT02 CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        profile = StaffProfile.objects.create(
            id=f"tgt02-cceo-sp-{suffix}", user=holder, title="CCEO"
        )
        today = date.today()
        allocation = MilestoneAllocation.objects.create(
            milestone=milestone,
            allocated_to_type="employee",
            employee=profile,
            allocated_target=10,
            allocation_reason="TGT02 fixture",
            allocated_by="tgt02",
            effective_date=today,
            status="approved",
        )
        period = MilestonePeriodTarget.objects.create(
            milestone=milestone,
            allocation=allocation,
            scope="employee",
            employee=profile,
            period_type="month",
            period_start=today.replace(day=1),
            period_end=today.replace(day=monthrange(today.year, today.month)[1]),
            planned_value=1,
            actual_value=0,
        )
        activity = Activity.objects.create(
            activity_type="school_visit",
            catalogue_item=item,
            delivery_type="staff",
            # Required for the credit engine to consider it at all (AUD-009):
            # without the reference the activity is skipped before any rule is
            # reached, and this test would prove nothing.
            salesforce_activity_id=f"VS-TGT02-{suffix.upper()}",
            responsible_staff_id=profile.id,
            status="ia_verified",
            school=self.school,
            planned_date=today,
            scheduled_date=timezone.now(),
            fy="2027",
        )
        record_activity_progress(activity)
        return activity, period

    def _assert_credited(self, activity, period):
        """The guard that stops the reversal assertions passing tautologically."""
        from apps.hr.models import MilestoneProgressCredit

        self.assertTrue(
            MilestoneProgressCredit.objects.filter(
                activity=activity, reversed_at__isnull=True
            ).exists(),
            "the fixture never reached the credit engine, so this test proves "
            "nothing — check milestone.active, the catalogue item and the "
            "Salesforce reference",
        )
        period.refresh_from_db()
        self.assertEqual(
            period.actual_value,
            1,
            "the verified activity did not move the period actual, so the "
            "reversal assertions below would hold for the wrong reason",
        )

    def _assert_reversed(self, activity, period, action: str):
        from apps.hr.models import MilestoneProgressCredit

        credit = MilestoneProgressCredit.objects.get(activity=activity)
        self.assertIsNotNone(
            credit.reversed_at,
            f"the {action} activity kept its milestone credit — called-off "
            "work is still being counted as verified achievement",
        )
        self.assertTrue(
            credit.reversed_reason,
            "the reversal recorded no reason: credits are append-only audit "
            "history and must say why the value was withdrawn",
        )
        period.refresh_from_db()
        self.assertEqual(
            period.actual_value,
            0,
            f"the period still reports achievement from {action} work",
        )

    def test_cancelling_a_verified_activity_reverses_its_credit(self):
        activity, period = self._verified_activity_with_credit("cancel")
        self._assert_credited(activity, period)

        # Through the real service, not a status write: a status write would
        # prove nothing about the door users actually go through.
        with self.captureOnCommitCallbacks(execute=True):
            asvc.cancel(activity.id, {"reason": "School closed"}, self.admin)

        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")
        self._assert_reversed(activity, period, "cancelled")

    def test_deferring_a_verified_activity_reverses_its_credit(self):
        activity, period = self._verified_activity_with_credit("defer")
        self._assert_credited(activity, period)

        with self.captureOnCommitCallbacks(execute=True):
            asvc.defer(activity.id, {"reason": "Moved to next term"}, self.admin)

        activity.refresh_from_db()
        self.assertEqual(activity.status, "deferred")
        self._assert_reversed(activity, period, "deferred")
