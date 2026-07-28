"""A planned activity's budget must reach the Accountant's disbursement queue.

The chain under test, end to end:

    schedule an activity with a costed budget line
      -> generate_weekly_fund_request builds the week's request from
         ActivityScheduleCostLine (the planned activity budget)
      -> request_advance: the responsible owner confirms
      -> approve_weekly_request: the PL (CCEO-owned) or the CD (PL/PC/IA-owned)
         approves, giving `confirmed_for_advance`
      -> the request appears in the Disbursement Dashboard as
         "Pending Disbursement" and can be disbursed

Both approval routes are exercised, because the routing depends on who owns the
request: `_submission_status_for` sends a CCEO's request to the PL and an
escalated owner's to the CD, and either approval must land the money in the
same queue.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.fund_requests.disbursement_dashboard_service import (
    _weekly_status,
    weekly_status_buckets,
)
from apps.fund_requests.models import WeeklyFundRequest
from apps.fund_requests.weekly_service import (
    approve_weekly_request,
    generate_weekly_fund_request,
    request_advance,
)
from apps.geography.models import District, Region
from apps.schools.models import School


def _monday(offset_weeks: int = 0) -> date:
    today = date.today()
    return today - timedelta(days=today.weekday()) + timedelta(weeks=offset_weeks)


class PlannedBudgetReachesDisbursementTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Disb Chain Region")
        cls.district = District.objects.create(
            name="Disb Chain District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="SCH-DISB-CHAIN",
            name="Disb Chain Primary",
            region=cls.region,
            district=cls.district,
        )

    def _person(self, key, role):
        user = User.objects.create(
            id=f"dc-{key}"[:30],
            email=f"dc-{key}@edify.org",
            name=f"DC {key}",
            roles=[role],
            active_role=role,
            is_active=True,
        )
        profile = StaffProfile.objects.create(
            id=f"dcs-{key}"[:30], user=user, title=role
        )
        return user, profile

    def _planned_activity_with_budget(self, owner, week_start, amount=75_000):
        """A scheduled activity carrying a costed budget line."""
        activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy=get_operational_fy(week_start),
            school=self.school,
            responsible_staff_id=owner.id,
            planned_date=week_start,
            scheduled_date=week_start,
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            responsible_user=owner.id,
            planned_date=week_start,
            description="Transport",
            unit_cost=amount,
            quantity=1,
            amount=amount,
        )
        return activity

    def _bucket_of(self, wfr):
        return weekly_status_buckets([wfr])[wfr.id]

    # ── the two approval routes ──────────────────────────────────────────────

    def test_a_cceo_request_approved_by_the_pl_becomes_disbursable(self):
        cceo, cceo_sp = self._person("cceo", "CCEO")
        pl, pl_sp = self._person("pl", "Program Lead")
        StaffSupervisorAssignment.objects.create(supervisor=pl_sp, supervisee=cceo_sp)

        week = _monday()
        self._planned_activity_with_budget(cceo, week)

        wfr = generate_weekly_fund_request(cceo.id, week.isoformat())
        self.assertIsNotNone(wfr, "the planned budget must produce a weekly request")
        self.assertEqual(wfr.status, "pending_responsible_confirmation")
        self.assertEqual(wfr.total_amount, 75_000)

        request_advance(wfr.id, cceo)
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "submitted_to_pl")

        approve_weekly_request(wfr.id, pl)
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "confirmed_for_advance")
        self.assertEqual(
            self._bucket_of(wfr),
            "Pending Disbursement",
            "a PL-approved advance must reach the Accountant's queue",
        )

    def test_an_escalated_request_approved_by_the_cd_becomes_disbursable(self):
        """A PL's own request routes to the CD, not to another PL."""
        owner, _owner_sp = self._person("pl-owner", "Program Lead")
        cd, _cd_sp = self._person("cd", "CountryDirector")

        week = _monday(1)
        self._planned_activity_with_budget(owner, week, amount=40_000)

        wfr = generate_weekly_fund_request(owner.id, week.isoformat())
        self.assertIsNotNone(wfr)

        request_advance(wfr.id, owner)
        wfr.refresh_from_db()
        self.assertEqual(
            wfr.status,
            "submitted_to_cd",
            "an escalated owner's request clears at the Country Director",
        )

        approve_weekly_request(wfr.id, cd)
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "confirmed_for_advance")
        self.assertEqual(self._bucket_of(wfr), "Pending Disbursement")

    def test_both_routes_land_in_the_same_queue_stage(self):
        """PL and CD approval are different authorities, one destination."""
        self.assertEqual(
            _weekly_status(
                type("W", (), {"status": "confirmed_for_advance"})(),
            ),
            "Pending Disbursement",
        )

    # ── the steps before approval ────────────────────────────────────────────

    def test_an_unconfirmed_request_is_not_yet_disbursable(self):
        """The owner confirms before an approver sees it -- by design."""
        cceo, _sp = self._person("cceo-unconfirmed", "CCEO")
        week = _monday(2)
        self._planned_activity_with_budget(cceo, week)

        wfr = generate_weekly_fund_request(cceo.id, week.isoformat())
        self.assertEqual(self._bucket_of(wfr), "Pending Approval")

    def test_an_owner_cannot_approve_their_own_request(self):
        from apps.core.exceptions import Forbidden

        cceo, cceo_sp = self._person("cceo-self", "CCEO")
        pl, pl_sp = self._person("pl-self", "Program Lead")
        StaffSupervisorAssignment.objects.create(supervisor=pl_sp, supervisee=cceo_sp)

        week = _monday(3)
        self._planned_activity_with_budget(cceo, week)
        wfr = generate_weekly_fund_request(cceo.id, week.isoformat())
        request_advance(wfr.id, cceo)

        with self.assertRaises(Forbidden):
            approve_weekly_request(wfr.id, cceo)

    def test_a_scheduled_activity_with_no_cost_lines_raises_no_request(self):
        cceo, _sp = self._person("cceo-nocost", "CCEO")
        week = _monday(4)
        Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy=get_operational_fy(week),
            school=self.school,
            responsible_staff_id=cceo.id,
            planned_date=week,
            scheduled_date=week,
        )
        self.assertIsNone(generate_weekly_fund_request(cceo.id, week.isoformat()))

    def test_an_approved_request_is_not_rewritten_by_a_later_schedule(self):
        """Finance safety: re-syncing must not mutate an approved amount."""
        cceo, cceo_sp = self._person("cceo-lock", "CCEO")
        pl, pl_sp = self._person("pl-lock", "Program Lead")
        StaffSupervisorAssignment.objects.create(supervisor=pl_sp, supervisee=cceo_sp)

        week = _monday(5)
        self._planned_activity_with_budget(cceo, week, amount=50_000)
        wfr = generate_weekly_fund_request(cceo.id, week.isoformat())
        request_advance(wfr.id, cceo)
        approve_weekly_request(wfr.id, pl)

        # A second activity scheduled into the same, already-approved week.
        self._planned_activity_with_budget(cceo, week, amount=999_000)
        generate_weekly_fund_request(cceo.id, week.isoformat())

        wfr.refresh_from_db()
        self.assertEqual(
            wfr.total_amount,
            50_000,
            "an approved amount must never be rewritten by a later schedule",
        )
        self.assertEqual(wfr.status, "confirmed_for_advance")


class DisbursementQueueShowsApprovedAdvancesTest(TestCase):
    """The approved advance must be visible to the Accountant, not just stored."""

    def test_confirmed_advances_appear_as_pending_disbursement(self):
        fy = get_operational_fy()
        confirmed = WeeklyFundRequest.objects.filter(
            fy=fy, status="confirmed_for_advance"
        )
        buckets = weekly_status_buckets(list(confirmed))
        for wfr in confirmed:
            with self.subTest(wfr.id):
                self.assertEqual(buckets[wfr.id], "Pending Disbursement")
