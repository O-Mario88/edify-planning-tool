from django.test import TestCase

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activity_catalogue.health import catalogue_health
from apps.activity_catalogue.models import ActivityCatalogueItem


class CatalogueRateHealthSemanticsTests(TestCase):
    def _line(self, activity, key, profile):
        return ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key=key,
            label="Test rate",
            unit_cost=40000,
            quantity=1,
            amount=40000,
            total_cost=40000,
            costing_profile=profile,
        )

    def _staff_rate_check(self):
        return next(
            check
            for check in catalogue_health()["checks"]
            if check["key"] == "catalogue_staff_cost_rate"
        )

    def test_staff_owned_partner_meeting_uses_its_governed_admin_rate(self):
        item = ActivityCatalogueItem.objects.get(stable_code="PARTNER_MEETINGS_ADMIN")
        activity = Activity.objects.create(
            activity_type="partner_activity",
            delivery_type="staff",
            status="scheduled",
            catalogue_item=item,
        )
        self._line(activity, "partner_visit_lump_sum", "ADMIN_PARTNER_MEETING")

        self.assertEqual(self._staff_rate_check()["status"], "pass")

    def test_other_staff_activity_with_partner_rate_still_fails_closed(self):
        item = ActivityCatalogueItem.objects.get(stable_code="STANDARD_SCHOOL_VISIT")
        activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            catalogue_item=item,
        )
        self._line(activity, "partner_visit_lump_sum", "STAFF_SCHOOL_VISIT")

        check = self._staff_rate_check()
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["count"], 1)
