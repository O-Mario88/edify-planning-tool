"""Regression tests: activities.services writes that touch multiple tables
(Activity + ActivityScheduleCostLine + downstream leave-budget sync) must be
atomic. A crash mid-sequence must never leave a scheduled Activity persisted
with zero budget lines, and a reschedule must never half-apply — leaving the
saved scheduled_date out of sync with the activity's own budget lines.
"""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.activities import services as asvc
from apps.activities.models import Activity
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.enums import ActivityType
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()
FY = "2026"


class ActivitySchedulingAtomicityTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.school = School.objects.create(
            school_id="SCH-ATOMIC-1",
            name="Atomic Test School",
            region=self.region,
            district=self.district,
        )
        # Admin is a country-scope role — bypasses the school/cluster
        # assignment fixtures that are irrelevant to this atomicity test.
        self.admin = User.objects.create_user(
            email="admin-atomic@edify.org",
            name="Ada Admin",
            roles=["Admin"],
            active_role="Admin",
            password="x",
            is_active=True,
        )
        # get_or_create/update_or_create: a default active catalogue (and its
        # global-unique rate keys) may already be seeded by a data migration,
        # so reuse it rather than colliding with it.
        catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda",
            fy=FY,
            version=1,
            defaults={"is_active": True, "label": "Atomic Test Catalogue"},
        )
        catalogue.is_active = True
        catalogue.save(update_fields=["is_active"])
        for key, cost in (
            ("staff_visit_transport_primary", 100_000),
            ("lunch", 20_000),
        ):
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key,
                    "unit_cost": cost,
                    "fy": FY,
                    "catalogue": catalogue,
                    "version": 1,
                },
            )

    def _create_data(self, scheduled_date="2026-07-20", **overrides):
        # core_visit is a school-visit type that is NOT daily-visit-batch
        # eligible, so reschedule() takes the plain re-price branch rather
        # than the (separately-atomic) batch branch — keeping this test
        # focused on the specific 3-write sequence under test.
        data = {
            "activityType": ActivityType.CORE_VISIT,
            "schoolId": self.school.school_id,
            "scheduledDate": scheduled_date,
            "activityPurposeText": "Routine visit",
            "focusIntervention": "teaching_environment",
            "districtType": "primary",
        }
        data.update(overrides)
        return data

    # ── create(): Activity + cost snapshot must land together ───────────────
    def test_costing_crash_leaves_no_orphan_activity(self):
        """If the cost snapshot fails right after Activity.objects.create(),
        create() must roll back the whole thing — never leaving a scheduled
        Activity persisted with zero budget lines."""
        acts_before = Activity.objects.count()
        with patch(
            "apps.budget.costing_service.ActivityScheduleCostLine.objects.bulk_create",
            side_effect=RuntimeError("simulated crash mid-write"),
        ):
            with self.assertRaises(RuntimeError):
                asvc.create(self._create_data(), self.admin)

        self.assertEqual(Activity.objects.count(), acts_before)
        self.assertFalse(
            Activity.objects.filter(
                school=self.school, activity_purpose_text="Routine visit"
            ).exists()
        )

    def test_successful_create_still_writes_activity_and_lines(self):
        """Sanity check: the happy path still works after wrapping in atomic()."""
        result = asvc.create(self._create_data(), self.admin)
        activity = Activity.objects.get(id=result["id"])
        self.assertGreater(activity.schedule_cost_lines.count(), 0)
        self.assertGreater(activity.est_cost_cents, 0)

    # ── reschedule(): schedule save + re-price + leave-budget sync ──────────
    def test_reschedule_crash_rolls_back_schedule_change(self):
        """A failure late in reschedule() (the leave-budget-impact rewrite of
        cost lines) must roll back the earlier scheduled_date/status save too
        — never leaving the Activity's persisted schedule out of sync with
        its own budget lines."""
        result = asvc.create(self._create_data(), self.admin)
        activity_id = result["id"]
        before = Activity.objects.get(id=activity_id)
        old_date = before.scheduled_date
        old_reschedule_count = before.reschedule_count
        old_line_planned_date = before.schedule_cost_lines.first().planned_date

        with patch(
            "apps.hr.leave_services.LeaveBudgetImpactService.handle_reschedule",
            side_effect=RuntimeError("simulated crash during leave-budget sync"),
        ):
            with self.assertRaises(RuntimeError):
                asvc.reschedule(
                    activity_id,
                    {
                        "scheduledDate": "2026-07-27T00:00:00",
                        "reason": "test reschedule",
                        "districtType": "primary",
                    },
                    self.admin,
                )

        activity = Activity.objects.get(id=activity_id)
        self.assertEqual(activity.scheduled_date, old_date)
        self.assertEqual(activity.reschedule_count, old_reschedule_count)
        # The budget line's planned_date (rewritten by apply_to_activity as
        # part of the same sequence) must also still point at the old date.
        self.assertEqual(
            activity.schedule_cost_lines.first().planned_date, old_line_planned_date
        )

    def test_successful_reschedule_still_updates_schedule_and_lines(self):
        """Sanity check: the happy path still works after wrapping in atomic()."""
        result = asvc.create(self._create_data(), self.admin)
        activity_id = result["id"]
        old_date = Activity.objects.get(id=activity_id).scheduled_date

        asvc.reschedule(
            activity_id,
            {
                "scheduledDate": "2026-07-27T00:00:00",
                "reason": "test reschedule",
                "districtType": "primary",
            },
            self.admin,
        )

        activity = Activity.objects.get(id=activity_id)
        self.assertNotEqual(activity.scheduled_date, old_date)
        self.assertEqual(activity.reschedule_count, 1)
        self.assertGreater(activity.schedule_cost_lines.count(), 0)
