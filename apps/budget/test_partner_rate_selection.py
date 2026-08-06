"""Partner scheduling prices against the partner rate card, on the right date.

The rate card is scoped by country, fiscal year and catalogue version — there
are no effective-from/effective-to windows on a rate, so "the rate effective on
the scheduled date" resolves to "the active catalogue for the FY that date
falls in". These tests hold the two things that can actually go wrong: pricing
partner delivery at a staff rate, and pricing it against the period the work
was handed over in rather than the period it will happen in.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.costing_service import apply_to_activity
from apps.budget.models import CostCatalogue, CostSetting
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School

STAFF_VISIT_RATE = 12_000
PARTNER_VISIT_RATE = 180_000


class PartnerRateSelectionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="s1", name="School A", district=cls.district, region=cls.region
        )
        cls.partner = Partner.objects.create(name="Partner X", active_status=True)

        # The FY2026 catalogue already exists — reference data publishes one on
        # migrate. Reuse it rather than creating a second, which the
        # one-active-catalogue-per-country-and-FY constraint rejects.
        cls.catalogue_2026, _ = CostCatalogue.objects.get_or_create(
            country="Uganda", fy="2026", version=1, defaults={"is_active": True}
        )
        for key, label, rate in (
            ("partner_visit_lump_sum", "Partner visit", PARTNER_VISIT_RATE),
            ("school_visit_transport", "Staff transport", STAFF_VISIT_RATE),
        ):
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": label,
                    "unit_cost": rate,
                    "fy": "2026",
                    "catalogue": cls.catalogue_2026,
                },
            )

    def _activity(self, *, delivery_type, planned, partner=None):
        return Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy="2026",
            quarter="Q1",
            planned_date=planned,
            planned_month=planned.month,
            scheduled_date=planned,
            status="partner_scheduled" if partner else "scheduled",
            delivery_type=delivery_type,
            assigned_partner_id=partner.id if partner else None,
        )

    def _price(self, activity):
        """Price through the canonical service, exactly as scheduling does."""
        return apply_to_activity(
            activity,
            {
                "activityType": activity.activity_type,
                "deliveryType": activity.delivery_type,
                "schoolId": activity.school_id,
                "fy": activity.fy,
                "plannedDate": activity.planned_date.isoformat(),
            },
        )

    def _lines(self, activity):
        return list(
            ActivityScheduleCostLine.objects.filter(activity=activity).order_by("label")
        )

    def test_partner_delivery_is_priced_at_a_partner_rate(self):
        activity = self._activity(
            delivery_type="partner", planned=date(2026, 4, 10), partner=self.partner
        )

        self._price(activity)

        lines = self._lines(activity)
        self.assertTrue(lines, "a scheduled partner activity must carry cost lines")
        keys = {line.cost_setting_key for line in lines}
        self.assertTrue(
            any("partner" in key for key in keys),
            f"expected a partner rate key, got {keys}",
        )

    def test_partner_delivery_is_never_priced_at_the_staff_rate(self):
        partner_work = self._activity(
            delivery_type="partner", planned=date(2026, 4, 10), partner=self.partner
        )
        staff_work = self._activity(delivery_type="staff", planned=date(2026, 4, 10))

        self._price(partner_work)
        self._price(staff_work)

        partner_total = sum(line.amount for line in self._lines(partner_work))
        staff_total = sum(line.amount for line in self._lines(staff_work))

        self.assertEqual(partner_total, PARTNER_VISIT_RATE)
        self.assertNotEqual(
            partner_total,
            staff_total,
            "partner delivery priced identically to staff delivery",
        )

    def test_the_cost_lines_carry_the_partner_they_belong_to(self):
        activity = self._activity(
            delivery_type="partner", planned=date(2026, 4, 10), partner=self.partner
        )

        self._price(activity)

        for line in self._lines(activity):
            with self.subTest(line=line.label):
                self.assertEqual(line.partner_id, self.partner.id)

    def test_the_cost_snapshot_records_the_catalogue_it_was_priced_against(self):
        """An activity must trace back to the rate card that priced it."""
        activity = self._activity(
            delivery_type="partner", planned=date(2026, 4, 10), partner=self.partner
        )

        self._price(activity)

        line = self._lines(activity)[0]
        self.assertEqual(line.catalogue_id, self.catalogue_2026.id)
        self.assertEqual(line.catalogue_version, self.catalogue_2026.version)

    def test_the_line_periods_follow_the_scheduled_date(self):
        """Not the handover date: cost lands in the period the work happens in."""
        activity = self._activity(
            delivery_type="partner", planned=date(2026, 4, 10), partner=self.partner
        )

        self._price(activity)

        line = self._lines(activity)[0]
        self.assertEqual(line.planned_date, date(2026, 4, 10))
        self.assertEqual(line.month, 4)
        self.assertEqual(line.fiscal_year, "2026")

    def test_pricing_replaces_rather_than_accumulates(self):
        """Rescheduling must not leave the old cost behind beside the new one."""
        activity = self._activity(
            delivery_type="partner", planned=date(2026, 4, 10), partner=self.partner
        )

        self._price(activity)
        first = sum(line.amount for line in self._lines(activity))
        self._price(activity)
        second = sum(line.amount for line in self._lines(activity))

        self.assertEqual(first, second, "re-pricing doubled the cost")
