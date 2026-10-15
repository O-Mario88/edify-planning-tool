"""A cost line that no weekly request will ever carry says why (owner,
2026-10-15: "can you double check all the budget, cost fetching and activity
costs. I feel like everything is off").

Read on production the same day: on a school visit every line read "Included
in Weekly Request" except Transport, which read "Draft Costed" — as if the
largest cost of the day had been left out. It is paid to the transport
company, by rule (apps.fund_requests.fundable.vendor_direct_filter). A
partner-facilitated training's fee read the same, though the partner's
invoice pays it; and a training planned with no participant count read
"Draft Costed" on every line, though none of it can be requested until the
count is entered. The words now follow the one rule that leaves each line out
(apps.fund_requests.fundable.fundable_lines).
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activities.test_finished_early import FinishedEarlyWorld
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School


class FundingStatusWords(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Words Region")
        district = District.objects.create(name="Words District", region=region)
        cls.school = School.objects.create(
            school_id="FSW-1", name="Words Primary", region=region, district=district
        )
        cls.partner = Partner.objects.create(name="Words Partner")
        cls.day = date.today() + timedelta(days=10)

    def _work(self, **extra):
        from datetime import datetime, time

        from django.utils import timezone

        values = {
            "activity_type": "school_visit",
            "school": self.school,
            "status": "scheduled",
            "delivery_type": "staff",
            "fy": "2027",
            "planned_date": self.day,
            "scheduled_date": timezone.make_aware(datetime.combine(self.day, time(9))),
            "responsible_staff_id": "staff-1",
        }
        values.update(extra)
        return Activity.objects.create(**values)

    def _line(self, activity, kind, **extra):
        values = {
            "cost_setting_key": kind,
            "line_item_type": kind,
            "label": kind.title(),
            "unit_cost": 10_000,
            "quantity": 1,
            "amount": 10_000,
        }
        values.update(extra)
        return ActivityScheduleCostLine.objects.create(activity=activity, **values)

    def _batch(self, visit):
        from apps.daily_visit_batches.models import DailyVisitBatch

        batch = DailyVisitBatch.objects.create(
            responsible_user="staff-1", visit_date=self.day, district_type="primary"
        )
        Activity.objects.filter(pk=visit.pk).update(daily_visit_batch=batch)
        visit.refresh_from_db()
        return batch

    def test_school_visit_transport_waits_on_the_transport_company(self):
        visit = self._work()
        self.assertEqual(
            self._line(visit, "transport").finance_status,
            "Transport Company: Awaiting Payment",
        )
        # The officer's own money still waits for its request.
        self.assertEqual(self._line(visit, "lunch").finance_status, "Draft Costed")

    def test_paid_only_once_the_transport_company_is_paid(self):
        from apps.fund_requests.finance_models import TransportPayment

        visit = self._work()
        batch = self._batch(visit)
        payment = TransportPayment.objects.create(
            batch=batch, provider_name="Provider", amount=10_000
        )
        line = self._line(visit, "transport")
        self.assertEqual(line.finance_status, "Transport Company: Awaiting Payment")
        TransportPayment.objects.filter(pk=payment.pk).update(status="paid")
        line = ActivityScheduleCostLine.objects.get(pk=line.pk)
        self.assertEqual(line.finance_status, "Paid to Transport Company")

    def test_a_hotel_finance_booked(self):
        visit = self._work()
        line = self._line(visit, "accommodation", vendor_paid=True)
        self.assertEqual(line.finance_status, "Hotel Booked by Finance")

    def test_a_partners_fee_follows_its_invoice_payments(self):
        from apps.fund_requests.finance_models import PartnerPayment

        training = self._work(
            activity_type="training", facilitating_partner_id=self.partner.id
        )
        fee = self._line(training, "facilitation")
        self.assertEqual(fee.finance_status, "Partner Invoice: Not Yet Paid")
        self.assertEqual(self._line(training, "venue").finance_status, "Draft Costed")
        paid = {
            "partner_name": "Words Partner",
            "amount_paid": 5_000,
            "payment_method": "bank",
            "payment_reference": "R1",
            "paid_by": "acct",
        }
        PartnerPayment.objects.create(activity=training, payment_type="advance", **paid)
        fee = ActivityScheduleCostLine.objects.get(pk=fee.pk)
        self.assertEqual(fee.finance_status, "Partner Invoice: 50% Paid")
        PartnerPayment.objects.create(
            activity=training,
            payment_type="clearance",
            **{**paid, "payment_reference": "R2"},
        )
        fee = ActivityScheduleCostLine.objects.get(pk=fee.pk)
        self.assertEqual(fee.finance_status, "Paid on Partner Invoice")

    def test_partner_delivered_work_is_on_its_invoice(self):
        work = self._work(delivery_type="partner", assigned_partner_id=self.partner.id)
        self.assertEqual(
            self._line(work, "transport").finance_status,
            "Partner Invoice: Not Yet Paid",
        )

    def test_called_off_work_is_not_funded(self):
        for status, words in (
            ("cancelled", "Not Funded: Cancelled"),
            ("deferred", "Not Funded: Deferred"),
        ):
            with self.subTest(status=status):
                visit = self._work(status=status)
                self.assertTrue(
                    self._line(visit, "transport").finance_status.startswith(
                        "Not Funded:"
                    )
                )
                self.assertEqual(self._line(visit, "lunch").finance_status, words)

    def test_unscheduled_work_is_not_funded(self):
        visit = self._work(scheduled_date=None)
        self.assertEqual(
            self._line(visit, "lunch").finance_status, "Not Funded: Not Scheduled"
        )

    def test_a_plan_missing_its_cost_cannot_be_requested(self):
        training = self._work(activity_type="training", cost_missing=True)
        self.assertEqual(
            self._line(training, "venue").finance_status,
            "Not Requested: Cost Setup Required",
        )

    def test_a_line_worth_nothing_says_its_rate_is_not_set(self):
        visit = self._work()
        self.assertEqual(
            self._line(visit, "lunch", unit_cost=0, amount=0).finance_status,
            "No Cost: Rate Not Set",
        )

    def test_the_owner_chose_not_to_request(self):
        from apps.fund_requests.models import AdvanceRequest

        visit = self._work()
        line = self._line(visit, "lunch")
        AdvanceRequest.objects.create(
            activity=visit,
            budget_line=line,
            responsible_user_id="staff-1",
            amount=10_000,
            status="not_requested",
        )
        line = ActivityScheduleCostLine.objects.get(pk=line.pk)
        self.assertEqual(line.finance_status, "Not Requested")


class TheActivityPageNamesAMissingHeadCount(FinishedEarlyWorld):
    """A training with no participant count was told "Minimum viable cost not
    configured. Ask the Country Director to set the missing rates" — four
    group trainings on production, none missing a rate (2026-10-15)."""

    def test_it_asks_for_the_participants_not_for_rates(self):
        from django.test import Client
        from django.utils import timezone

        from apps.budget.models import ActivityCostSnapshot

        training = Activity.objects.create(
            activity_type="training",
            school=self.school,
            fy=self.early.fy,
            planned_date=self.ahead,
            responsible_staff_id=self.staff.id,
            delivery_type="staff",
            status="scheduled",
            cost_missing=True,
        )
        ActivityCostSnapshot.objects.create(
            activity=training,
            is_current=True,
            missing_configuration=["expectedParticipants"],
            calculated_at=timezone.now(),
        )
        client = Client()
        client.force_login(self.user)
        response = client.get(f"/my-plan/{training.id}")
        self.assertContains(response, "No participant count is planned")
        # A cost that could not be priced is not UGX 0.
        self.assertContains(response, "Not priced")
        self.assertNotContains(response, "Ask the Country Director to set the missing")
