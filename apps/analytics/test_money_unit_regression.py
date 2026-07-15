"""Regression test for the UGX-vs-cents money-unit bug found in the
2026-07-15 system audit: leadership_summary()'s disbursedTotalUgx used to
divide Sum(est_cost_cents) by 100, understating the real disbursed total by
100x. est_cost_cents holds plain UGX despite its name (see
apps.budget.costing_service, the sole writer) -- there is no cents scaling
anywhere in this codebase outside apps.professional_development.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.activities.models import Activity, ActivityType
from apps.analytics import services
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class LeadershipSummaryMoneyUnitTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin-money-unit@test.org",
            name="Money Unit Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="password",
            is_active=True,
        )
        region = Region.objects.create(name="Analytics Money Unit Region")
        district = District.objects.create(
            name="Analytics Money Unit District", region=region
        )
        self.school = School.objects.create(
            school_id="AMU-SCH",
            name="Analytics Money Unit School",
            region=region,
            district=district,
        )
        self.fy = "2026"
        Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="closed",
            payment_status="paid",
            fy=self.fy,
            salesforce_activity_id="SV-AMU-0001",
            est_cost_cents=300000,
        )
        Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="ia_verified",
            payment_status="ia_confirmed",
            fy=self.fy,
            est_cost_cents=150000,
        )

    def test_disbursed_total_ugx_is_not_divided_by_100(self):
        result = services.leadership_summary(self.admin, {"fy": self.fy})
        self.assertEqual(result["disbursedTotalUgx"], 450000)
