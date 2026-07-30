"""Regression tests for the 2026-07-30 planning→costing→budget audit fixes.

One scheduled Activity must produce one authoritative record, one complete
cost set from the CD Cost Catalogue, one contribution per budget period, and
one valid funding path — no duplication, omission, stale totals, or second
payable channel.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase

from apps.activities import services as asvc
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.models import CostSetting
from apps.core.exceptions import BadRequest
from apps.fund_requests.models import (
    AdvanceRequest,
    WeeklyFundRequest,
    WeeklyFundRequestLine,
)
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School

User = get_user_model()


class _PipelineFixture(TransactionTestCase):
    """TransactionTestCase on purpose: partner_schedule's row lock previously
    sat OUTSIDE transaction.atomic(), which TestCase's implicit wrapping
    masked (select_for_update outside a transaction is an error in
    production autocommit)."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email="audit-admin@edify.org",
            name="Audit Admin",
            roles=["Admin"],
            active_role="Admin",
            password="x",
            is_active=True,
        )
        self.region = Region.objects.create(name="Audit Region")
        self.district = District.objects.create(
            name="Audit District", region=self.region, district_type="primary"
        )
        self.school = School.objects.create(
            school_id="AUD-SCH-1",
            name="Audit School",
            school_type="partner",
            region=self.region,
            district=self.district,
        )
        self.partner = Partner.objects.create(name="Audit Partner")

    def _schedule_staff_visit(self, date_iso="2026-08-17T09:00:00+03:00", **over):
        data = {
            "activityType": "school_visit",
            "schoolId": self.school.school_id,
            "scheduledDate": date_iso,
            "focusIntervention": "leadership",
            "activityPurposeText": "Audit visit",
            **over,
        }
        return asvc.create(data, self.admin)


class OneActivityOneCostOneChannelTest(_PipelineFixture):
    def test_staff_visit_creates_cost_set_weekly_request_and_advances(self):
        result = self._schedule_staff_visit()
        activity = Activity.objects.get(id=result["id"])
        lines = activity.schedule_cost_lines.all()
        self.assertGreater(len(lines), 0)
        for line in lines:
            self.assertTrue(line.cost_setting_key)
            self.assertIsNotNone(line.catalogue_id)
            self.assertEqual(line.unit_cost * line.quantity, line.total_cost)
        # exactly one weekly draft carries the lines; advances mirror 1:1
        wfr_lines = WeeklyFundRequestLine.objects.filter(
            activity_budget_line__activity=activity
        )
        self.assertEqual(wfr_lines.count(), len(lines))
        self.assertEqual(
            AdvanceRequest.objects.filter(activity=activity).count(), len(lines)
        )

    def test_missing_rate_blocks_scheduling_with_no_partial_state(self):
        CostSetting.objects.all().delete()
        acts_before = Activity.objects.count()
        with self.assertRaises(BadRequest):
            self._schedule_staff_visit()
        self.assertEqual(Activity.objects.count(), acts_before)
        self.assertEqual(ActivityScheduleCostLine.objects.count(), 0)

    def test_cancel_withdraws_draft_funding(self):
        result = self._schedule_staff_visit()
        activity = Activity.objects.get(id=result["id"])
        self.assertTrue(AdvanceRequest.objects.filter(activity=activity).exists())

        asvc.cancel(activity.id, {"reason": "Rained out"}, self.admin)

        self.assertFalse(AdvanceRequest.objects.filter(activity=activity).exists())
        self.assertFalse(
            WeeklyFundRequestLine.objects.filter(
                activity_budget_line__activity=activity
            ).exists()
        )
        # cost lines stay as the historical snapshot
        self.assertTrue(activity.schedule_cost_lines.exists())
        for wfr in WeeklyFundRequest.objects.all():
            expected = sum(wl.total_cost for wl in wfr.lines.all())
            self.assertEqual(wfr.total_amount, expected)


class PartnerSingleChannelTest(_PipelineFixture):
    def test_partner_schedule_from_assignment_outside_atomic_and_costed_once(self):
        pa = PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.admin.id,
            expected_activity_type="school_visit",
            status="pending_scheduling",
        )
        # No outer transaction here — this is the production autocommit shape
        # that used to raise TransactionManagementError from the misplaced
        # select_for_update.
        result = asvc.partner_schedule(
            pa.id, {"scheduledDate": "2026-08-19T09:00:00+03:00"}, self.admin
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.delivery_type, "partner")
        self.assertTrue(activity.schedule_cost_lines.exists())

        # Partner cost must NOT enter the staff funding channels.
        self.assertFalse(AdvanceRequest.objects.filter(activity=activity).exists())
        self.assertFalse(
            WeeklyFundRequestLine.objects.filter(
                activity_budget_line__activity=activity
            ).exists()
        )

        # Scheduling the same assignment again is refused.
        with self.assertRaises(BadRequest):
            asvc.partner_schedule(
                pa.id, {"scheduledDate": "2026-08-20T09:00:00+03:00"}, self.admin
            )
        self.assertEqual(
            Activity.objects.filter(assigned_partner_id=self.partner.id).count(), 1
        )
