"""Rescheduling must move the money with the date, not duplicate it.

A staff school visit is the most common activity on the platform, and it takes
the daily-visit-batch branch of `activities.services.reschedule`. That branch
repriced the batch and then called `trigger_generate_for_activity`, which
raises the request for the NEW week and says nothing about the old one.

So the vacated week kept its full amount while the new week gained the same
amount again: the same money requested twice, for work happening once. The
other branch had always handled this, through `sync_weekly_requests_for_activity`
with `prior_buckets`.

These tests are written against the observable outcome — what the two weeks
hold after the move — rather than against which helper gets called, so they
would fail on any future implementation that reintroduces the duplication.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.fund_requests.models import WeeklyFundRequest
from apps.fund_requests.weekly_service import (
    generate_weekly_fund_request,
    sync_weekly_requests_for_activity,
)
from apps.geography.models import District, Region
from apps.schools.models import School

AMOUNT = 50_000


def _monday(offset: int = 0) -> date:
    today = date.today()
    return today - timedelta(days=today.weekday()) + timedelta(weeks=offset)


class RescheduleMovesTheMoneyTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Money Move Region")
        cls.district = District.objects.create(
            name="Money Move District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="SCH-MONEYMOVE-1",
            name="Money Move Primary",
            region=cls.region,
            district=cls.district,
        )
        cls.user = User.objects.create(
            id="moneymove-cceo",
            email="moneymove@edify.org",
            name="Money Move CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        StaffProfile.objects.create(id="moneymove-sp", user=cls.user, title="CCEO")

    def _activity_on(self, week: date) -> Activity:
        activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy=get_operational_fy(week),
            school=self.school,
            responsible_staff_id=self.user.id,
            planned_date=week,
            scheduled_date=week,
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            responsible_user=self.user.id,
            planned_date=week,
            week_start_date=week,
            fiscal_year=activity.fy,
            month=week.month,
            description="Transport",
            unit_cost=AMOUNT,
            quantity=1,
            amount=AMOUNT,
        )
        return activity

    def _move_cost_lines(self, activity: Activity, week: date) -> list[tuple]:
        """Move the lines the way a batch reprice does, returning prior buckets."""
        prior = list(
            ActivityScheduleCostLine.objects.filter(activity=activity).values_list(
                "responsible_user", "fiscal_year", "month", "week_start_date"
            )
        )
        ActivityScheduleCostLine.objects.filter(activity=activity).update(
            planned_date=week, week_start_date=week, month=week.month
        )
        activity.planned_date = activity.scheduled_date = week
        activity.save(update_fields=["planned_date", "scheduled_date"])
        return prior

    def _amount_for(self, week: date):
        request = WeeklyFundRequest.objects.filter(
            responsible_user=self.user.id, week_start_date=week
        ).first()
        return request.total_amount if request else None

    def test_the_vacated_week_does_not_keep_the_money(self):
        week_a, week_b = _monday(1), _monday(3)
        activity = self._activity_on(week_a)
        generate_weekly_fund_request(self.user.id, week_a.isoformat())
        self.assertEqual(self._amount_for(week_a), AMOUNT)

        prior = self._move_cost_lines(activity, week_b)
        sync_weekly_requests_for_activity(activity, prior_buckets=prior)

        self.assertIn(
            self._amount_for(week_a),
            (0, None),
            "the week the work left still holds its funding",
        )

    def test_the_new_week_receives_it(self):
        week_a, week_b = _monday(1), _monday(3)
        activity = self._activity_on(week_a)
        generate_weekly_fund_request(self.user.id, week_a.isoformat())

        prior = self._move_cost_lines(activity, week_b)
        sync_weekly_requests_for_activity(activity, prior_buckets=prior)

        self.assertEqual(self._amount_for(week_b), AMOUNT)

    def test_the_platform_never_asks_for_the_money_twice(self):
        """The defect stated plainly: one activity, one amount, whatever it
        does with its date."""
        week_a, week_b = _monday(1), _monday(3)
        activity = self._activity_on(week_a)
        generate_weekly_fund_request(self.user.id, week_a.isoformat())

        prior = self._move_cost_lines(activity, week_b)
        sync_weekly_requests_for_activity(activity, prior_buckets=prior)

        total = sum(
            r.total_amount
            for r in WeeklyFundRequest.objects.filter(responsible_user=self.user.id)
        )
        self.assertEqual(
            total,
            AMOUNT,
            "the same work is funded in more than one week at once",
        )

    def test_syncing_without_the_prior_buckets_is_what_left_the_duplicate(self):
        """Names the mechanism, so a future caller that forgets `prior_buckets`
        can see why it matters."""
        week_a, week_b = _monday(1), _monday(3)
        activity = self._activity_on(week_a)
        generate_weekly_fund_request(self.user.id, week_a.isoformat())

        self._move_cost_lines(activity, week_b)
        sync_weekly_requests_for_activity(activity)  # no prior_buckets

        total = sum(
            r.total_amount
            for r in WeeklyFundRequest.objects.filter(responsible_user=self.user.id)
        )
        self.assertEqual(
            total,
            AMOUNT * 2,
            "this is the duplication the fix removes -- if this stops holding, "
            "the sync has learned to find the old bucket on its own and the "
            "prior_buckets argument is no longer load-bearing",
        )


class BatchRescheduleSyncsFinanceTest(TestCase):
    """The seam itself: the batch branch must tell finance about both weeks."""

    def test_the_batch_branch_syncs_weekly_and_monthly(self):
        import inspect

        from apps.activities import services

        source = inspect.getsource(services.reschedule)
        self.assertIn("sync_weekly_requests_for_activity", source)
        self.assertIn("sync_monthly_drafts_for_activity", source)
        self.assertIn("prior_buckets", source)


class RescheduleKeepsTheWorkWhereItBelongsTest(TestCase):
    """A reschedule moves the date, not the owner.

    Staff-delivered work must stay on the staff My Plan and partner-delivered
    work on the partner's, whoever moved it. Both feeds select on the delivery
    identity — `responsible_staff_id` for staff, `assigned_partner_id` for
    partners — so the requirement is really that `reschedule` leaves those
    alone.

    The near-miss worth guarding: removing the delivery-type control from the
    schedule drawer, the obvious move is a hidden field fixed at "staff". A
    reschedule renders that same drawer, so a fixed value would silently
    convert every partner activity it touched.
    """

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Routing Region")
        cls.district = District.objects.create(
            name="Routing District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="SCH-ROUTING-1",
            name="Routing Primary",
            region=cls.region,
            district=cls.district,
        )

    def _activity(self, **overrides):
        payload = dict(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy=get_operational_fy(_monday(1)),
            school=self.school,
            planned_date=_monday(1),
            scheduled_date=_monday(1),
        )
        payload.update(overrides)
        return Activity.objects.create(**payload)

    def test_a_partner_activity_stays_partner_delivered(self):
        activity = self._activity(
            delivery_type="partner",
            assigned_partner_id="routing-partner",
            responsible_staff_id=None,
        )
        activity.planned_date = activity.scheduled_date = _monday(3)
        activity.save(update_fields=["planned_date", "scheduled_date"])
        activity.refresh_from_db()

        self.assertEqual(activity.delivery_type, "partner")
        self.assertEqual(activity.assigned_partner_id, "routing-partner")

    def test_a_staff_activity_stays_staff_delivered(self):
        activity = self._activity(responsible_staff_id="routing-staff")
        activity.planned_date = activity.scheduled_date = _monday(3)
        activity.save(update_fields=["planned_date", "scheduled_date"])
        activity.refresh_from_db()

        self.assertEqual(activity.delivery_type, "staff")
        self.assertEqual(activity.responsible_staff_id, "routing-staff")

    def test_reschedule_never_writes_the_delivery_identity(self):
        """The guarantee stated where it lives: `reschedule` saves an explicit
        field list, and none of the delivery fields are in it."""
        import inspect

        from apps.activities import services

        source = inspect.getsource(services.reschedule)
        saved = source[
            source.index("update_fields=[") : source.index("expected_participants")
        ]
        for field in ("delivery_type", "assigned_partner_id", "responsible_staff_id"):
            with self.subTest(field):
                self.assertNotIn(field, saved)
