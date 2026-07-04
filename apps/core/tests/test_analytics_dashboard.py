from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from datetime import timedelta

from apps.accounts.models import StaffProfile, User, StaffSchoolAssignment, StaffTargetProfile
from apps.activities.models import Activity
from apps.core.enums import ActivityType
from apps.core.rbac import EdifyRole
from apps.geography.models import Region, District, SubCounty
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.core.enums import SsaIntervention

class AnalyticsDashboardTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.sub_county = SubCounty.objects.create(name="Kampala Central", district=self.district)

        self.user = User.objects.create_user(
            email="cd@edify.org", name="CD Director",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value], active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="testpassword", is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.user, title="Country Director")
        
        self.school = School.objects.create(
            school_id="SCH-TEST", name="Test Academy", region=self.region,
            district=self.district, sub_county=self.sub_county,
            current_fy_ssa_status="done", planning_readiness="ready",
            enrollment=500
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)

        # Create target profile
        StaffTargetProfile.objects.create(
            staff=self.staff, fy="2026", visits_target=10, trainings_target=5
        )

        # Create an achieved activity
        Activity.objects.create(
            activity_type=ActivityType.SCHOOL_VISIT.value, school=self.school,
            responsible_staff_id=self.staff.id, fy="2026", quarter="Q2",
            planned_month=1, scheduled_date=timezone.now(),
            status="completed", evidence_status="accepted", salesforce_activity_id="SV-101",
            salesforce_activity_type="visit", teachers_attended=12, leaders_attended=3
        )

        # Create verified SSA record
        self.ssa = SsaRecord.objects.create(
            school=self.school, fy="2026", quarter="Q2",
            date_of_ssa=timezone.now() - timedelta(days=2),
            verification_status="confirmed", average_score=4.5
        )
        for i in SsaIntervention:
            SsaScore.objects.create(ssa_record=self.ssa, intervention=i.value, score=4.5)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("frontend:analytics_dashboard"))
        self.assertRedirects(response, "/login?next=/analytics")

    def test_dashboard_renders_successfully(self):
        self.client.login(email="cd@edify.org", password="testpassword")
        response = self.client.get(reverse("frontend:analytics_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Analytics")
        self.assertContains(response, "Kampala")
        self.assertContains(response, "Central Region")

    def test_htmx_partial_render(self):
        self.client.login(email="cd@edify.org", password="testpassword")
        response = self.client.get(reverse("frontend:analytics_dashboard"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        # Should render partial template containing the KPI cards, not the full layout shell
        self.assertNotContains(response, "<!DOCTYPE html>")
        self.assertContains(response, "Target Achievement")

    def test_drilldown_drawer_view(self):
        self.client.login(email="cd@edify.org", password="testpassword")
        url = reverse("frontend:analytics_drilldown") + "?metric=teachers_trained&fy=2026&quarter=Q2"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Trained Participants")
        self.assertContains(response, "SV-101")

    def test_schedule_report_drawer(self):
        self.client.login(email="cd@edify.org", password="testpassword")
        response = self.client.get(reverse("frontend:analytics_schedule_report"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Schedule Report")

    def test_customize_dashboard_drawer(self):
        self.client.login(email="cd@edify.org", password="testpassword")
        response = self.client.get(reverse("frontend:analytics_customize_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Customize Dashboard")
