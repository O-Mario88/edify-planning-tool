from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.geography.models import Region, District, SubCounty
from apps.schools.models import School
from apps.clusters.models import Cluster

class FrontendViewsTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        # Create users for different roles
        self.cceo_user = User.objects.create(
            id="cceo-1",
            email="cceo@edify.org",
            name="CCEO User",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True
        )
        self.cceo_user.set_password("pass123")
        self.cceo_user.save()

        # Create StaffProfile for CCEO
        self.cceo_profile = StaffProfile.objects.create(
            id="staff-cceo-1",
            user=self.cceo_user,
            title="CCEO"
        )

        # Create basic geography
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampola", region=self.region)
        self.sub_county = SubCounty.objects.create(name="Central Subcounty", district=self.district)

        # Create a school
        self.school = School.objects.create(
            school_id="SCH-99",
            name="Kampola High School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            current_fy_ssa_status="not_done",
            planning_readiness="locked"
        )

        # Assign CCEO to the school so it is in scope
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_profile,
            school_id=self.school.id
        )

        # Create a cluster
        self.cluster = Cluster.objects.create(
            name="Central Cluster One",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active"
        )

    def test_anonymous_redirect_to_login(self):
        # Unauthenticated users should be redirected to login page
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/login"))

    def test_dashboard_view_renders_successfully(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/dashboards/cceo.html")

    def test_schools_directory_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get("/schools")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/schools/index.html")

    def test_school_detail_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get(f"/schools/{self.school.school_id}")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/schools/detail.html")

    def test_clusters_directory_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get("/clusters")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/clusters/index.html")

    def test_cluster_detail_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get(f"/clusters/{self.cluster.id}")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/clusters/detail.html")

    def test_planning_dashboard_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get("/planning")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/planning/index.html")

    def test_monthly_budget_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get("/budgets/monthly")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/budgets/monthly.html")

    def test_weekly_fund_requests_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get("/fund-requests/weekly")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/fund_requests/weekly.html")

    def test_my_plan_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get("/my-plan")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/my_plan/index.html")

    def test_analytics_dashboard_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get("/analytics")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/analytics/index.html")

    def test_system_health_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get("/system-health")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/system_health/index.html")
