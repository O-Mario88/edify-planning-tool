"""School-visit mission channels — who gets paid what.

The full daily mission cost (transport + meals + accommodation) is planned
and visible to approvers; the CCEO's weekly advance carries only their
personal entitlements: lunch in the primary district; breakfast, lunch,
dinner and (unless Finance books the hotel) accommodation in a secondary
district. Transport is always paid direct to the transport company.
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden
from apps.fund_requests.fundable import fundable_lines
from apps.fund_requests.models import WeeklyFundRequest
from apps.fund_requests.vendor_channel import set_accommodation_vendor_paid
from apps.fund_requests.weekly_service import (
    generate_weekly_fund_request,
    request_advance,
)
from apps.geography.models import District, Region
from apps.schools.models import School


def _monday(offset_weeks=2):
    d = timezone.localdate() + datetime.timedelta(weeks=offset_weeks)
    return d - datetime.timedelta(days=d.weekday())


class _P:
    def __init__(self, user, role=None):
        self.user_id = user.id
        self.active_role = role or user.active_role
        self.staff_profile_id = None
        self.country_scope = False


class MissionChannelTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="MC Region")
        self.district = District.objects.create(
            name="MC District", region=self.region, district_type="secondary"
        )
        self.school = School.objects.create(
            school_id="MC-SCH",
            name="MC School",
            region=self.region,
            district=self.district,
        )
        User = get_user_model()
        self.cceo = User.objects.create(
            id="mc-cceo",
            email="mc-cceo@test.org",
            name="MC CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.cceo_sp = StaffProfile.objects.create(
            id="mc-sp", user=self.cceo, title="CCEO"
        )
        self.acct = User.objects.create(
            id="mc-acct",
            email="mc-acct@test.org",
            name="MC Accountant",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        self.week = _monday()

    def _visit_day(self, offset=0, district_type="secondary"):
        """One secondary-district visit day, priced per the day recipe."""
        day = self.week + datetime.timedelta(days=offset)
        activity = Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            responsible_staff_id=self.cceo_sp.id,
            fy="2026",
            scheduled_date=timezone.make_aware(
                datetime.datetime.combine(day, datetime.time(9))
            ),
        )
        recipe = {
            "secondary": (
                ("secondary_transport_per_day", "transport", 60_000),
                ("secondary_lunch_per_day", "lunch", 15_000),
                ("secondary_breakfast_per_day", "breakfast", 8_000),
                ("secondary_overnight_dinner_per_day", "dinner", 12_000),
                ("secondary_accommodation_per_night", "accommodation", 80_000),
            ),
            "primary": (
                ("primary_transport_per_day", "transport", 20_000),
                ("primary_lunch_per_day", "lunch", 10_000),
            ),
        }[district_type]
        for key, item_type, amount in recipe:
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                school=self.school,
                cost_setting_key=key,
                label=key.replace("_", " ").title(),
                line_item_type=item_type,
                unit_cost=amount,
                quantity=1,
                amount=amount,
                responsible_user=self.cceo.id,
                planned_date=day,
                week_start_date=self.week,
                week_end_date=self.week + datetime.timedelta(days=6),
                month=day.month,
                fiscal_year="2026",
                catalogue_id="cat-mc",
            )
        return activity

    # ── the channel rule ─────────────────────────────────────────────────────
    def test_secondary_day_advance_is_meals_and_accommodation_only(self):
        self._visit_day()
        wfr = generate_weekly_fund_request(self.cceo.id, self.week.isoformat())
        # breakfast + lunch + dinner + accommodation; transport excluded.
        self.assertEqual(wfr.total_amount, 15_000 + 8_000 + 12_000 + 80_000)

    def test_primary_day_advance_is_lunch_only(self):
        self._visit_day(district_type="primary")
        wfr = generate_weekly_fund_request(self.cceo.id, self.week.isoformat())
        self.assertEqual(wfr.total_amount, 10_000)

    def test_field_event_transport_stays_in_the_owners_advance(self):
        # No school on the activity → the owner arranges their own travel.
        day = self.week
        activity = Activity.objects.create(
            activity_type="field_event",
            delivery_type="staff",
            status="scheduled",
            responsible_staff_id=self.cceo_sp.id,
            fy="2026",
            scheduled_date=timezone.make_aware(
                datetime.datetime.combine(day, datetime.time(9))
            ),
        )
        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="secondary_transport_per_day",
            label="Transport",
            line_item_type="transport",
            unit_cost=66_000,
            quantity=1,
            amount=66_000,
            responsible_user=self.cceo.id,
            planned_date=day,
            week_start_date=self.week,
            week_end_date=self.week + datetime.timedelta(days=6),
            month=day.month,
            fiscal_year="2026",
            catalogue_id="cat-mc",
        )
        self.assertIn(
            line.id,
            set(
                fundable_lines(
                    ActivityScheduleCostLine.objects.filter(activity=activity)
                ).values_list("id", flat=True)
            ),
        )

    # ── Finance's accommodation decision ─────────────────────────────────────
    def test_finance_booking_the_hotel_removes_it_from_the_advance(self):
        activity = self._visit_day()
        wfr = generate_weekly_fund_request(self.cceo.id, self.week.isoformat())
        self.assertEqual(wfr.total_amount, 115_000)

        acc_line = activity.schedule_cost_lines.get(line_item_type="accommodation")
        set_accommodation_vendor_paid(acc_line.id, True, _P(self.acct))

        wfr.refresh_from_db()
        # meals only remain in the owner's advance
        self.assertEqual(wfr.total_amount, 15_000 + 8_000 + 12_000)

    def test_only_finance_may_decide_the_channel(self):
        activity = self._visit_day()
        acc_line = activity.schedule_cost_lines.get(line_item_type="accommodation")
        with self.assertRaises(Forbidden):
            set_accommodation_vendor_paid(acc_line.id, True, _P(self.cceo))

    def test_channel_cannot_change_under_a_submitted_request(self):
        activity = self._visit_day()
        wfr = generate_weekly_fund_request(self.cceo.id, self.week.isoformat())
        request_advance(wfr.id, _P(self.cceo))
        acc_line = activity.schedule_cost_lines.get(line_item_type="accommodation")
        with self.assertRaises(BadRequest):
            set_accommodation_vendor_paid(acc_line.id, True, _P(self.acct))
        self.assertEqual(WeeklyFundRequest.objects.get(id=wfr.id).total_amount, 115_000)

    def test_only_accommodation_can_move_channels(self):
        activity = self._visit_day()
        lunch = activity.schedule_cost_lines.get(line_item_type="lunch")
        with self.assertRaises(BadRequest):
            set_accommodation_vendor_paid(lunch.id, True, _P(self.acct))


class TransportProviderPaymentTest(TestCase):
    """§9.1 — one vendor obligation per mission day: created from the pooled
    transport component, refreshed while pending, immutable once paid, and
    never payable twice or by a non-finance role."""

    def setUp(self):
        from datetime import date

        from apps.daily_visit_batches.models import DailyVisitBatch

        User = get_user_model()
        self.acct = User.objects.create(
            id="tp-acct",
            email="tp-acct@test.org",
            name="TP Accountant",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        User.objects.create(
            id="tp-cceo",
            email="tp-cceo@test.org",
            name="TP CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.batch = DailyVisitBatch.objects.create(
            responsible_user="tp-cceo",
            visit_date=date(2026, 8, 7),
            district_type="primary",
            rate_snapshot={
                "primary_transport_per_day": 280_000,
                "primary_lunch_per_day": 30_000,
            },
            daily_pool_amount=310_000,
        )

    def _pay(self, principal, **overrides):
        from apps.fund_requests.vendor_channel import (
            ensure_transport_obligation,
            pay_transport_provider,
        )

        payment = ensure_transport_obligation(self.batch)
        data = {
            "provider_name": "Kampala Fleet Ltd",
            "payment_method": "Bank Transfer",
            "payment_reference": "EFT-TP-1",
            "netsuite_expense_id": "NS-TP-1",
            **overrides,
        }
        return pay_transport_provider(payment.id, data, principal)

    def test_obligation_carries_only_the_transport_component(self):
        from apps.fund_requests.vendor_channel import ensure_transport_obligation

        payment = ensure_transport_obligation(self.batch)
        self.assertEqual(payment.amount, 280_000)
        self.assertEqual(payment.status, "pending")

    def test_pending_obligation_refreshes_with_the_day(self):
        from apps.fund_requests.vendor_channel import ensure_transport_obligation

        ensure_transport_obligation(self.batch)
        self.batch.rate_snapshot["primary_transport_per_day"] = 300_000
        payment = ensure_transport_obligation(self.batch)
        self.assertEqual(payment.amount, 300_000)

    def test_accountant_pays_once_and_only_once(self):
        result = self._pay(_P(self.acct))
        self.assertEqual(result["status"], "paid")
        with self.assertRaises(BadRequest):
            self._pay(_P(self.acct), payment_reference="EFT-TP-2")

    def test_paid_obligation_never_rewrites_from_a_reprice(self):
        from apps.fund_requests.finance_models import TransportPayment
        from apps.fund_requests.vendor_channel import ensure_transport_obligation

        self._pay(_P(self.acct))
        self.batch.rate_snapshot["primary_transport_per_day"] = 999_000
        ensure_transport_obligation(self.batch)
        self.assertEqual(TransportPayment.objects.get(batch=self.batch).amount, 280_000)

    def test_reference_is_required_netsuite_is_not(self):
        with self.assertRaises(BadRequest):
            self._pay(_P(self.acct), payment_reference="")
        # NetSuite IDs are staff-accountability proof only (owner,
        # 2026-08-20) — the accountant pays the vendor directly, so an empty
        # NetSuite id is fine.
        result = self._pay(_P(self.acct), netsuite_expense_id="")
        self.assertTrue(result)

    def test_only_finance_may_pay_the_provider(self):
        cceo = get_user_model().objects.get(id="tp-cceo")
        with self.assertRaises(Forbidden):
            self._pay(_P(cceo))
