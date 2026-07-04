from rest_framework.test import APITestCase

from apps.accounts.models import User, StaffProfile, StaffSchoolAssignment
from apps.geography.models import Region, District
from apps.schools.models import School

class RoleGatingPermissionTest(APITestCase):
    def setUp(self):
        # Setup Geography
        self.region = Region.objects.create(name="East")
        self.district = District.objects.create(name="Mbale", region=self.region)

        # Setup Schools
        self.school_cceo1 = School.objects.create(
            school_id="S-CCEO-1",
            name="CCEO 1 School",
            region=self.region,
            district=self.district,
            enrollment=200,
            school_type="client"
        )
        self.school_cceo2 = School.objects.create(
            school_id="S-CCEO-2",
            name="CCEO 2 School",
            region=self.region,
            district=self.district,
            enrollment=300,
            school_type="client"
        )

        # Setup CCEO-1 User
        self.cceo1_user = User.objects.create_user(
            email="cceo1@edify.test",
            name="CCEO 1 User",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        self.cceo1_profile = StaffProfile.objects.create(
            user=self.cceo1_user,
            staff_number="ST-1001",
        )
        # Assign School 1 to CCEO 1
        StaffSchoolAssignment.objects.create(
            staff=self.cceo1_profile,
            school_id=self.school_cceo1.id
        )

        # Setup CCEO-2 User
        self.cceo2_user = User.objects.create_user(
            email="cceo2@edify.test",
            name="CCEO 2 User",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        self.cceo2_profile = StaffProfile.objects.create(
            user=self.cceo2_user,
            staff_number="ST-1002",
        )
        # Assign School 2 to CCEO 2
        StaffSchoolAssignment.objects.create(
            staff=self.cceo2_profile,
            school_id=self.school_cceo2.id
        )

        # Setup Country Director User (Strategic role)
        self.cd_user = User.objects.create_user(
            email="cd@edify.test",
            name="Country Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )
        self.cd_profile = StaffProfile.objects.create(
            user=self.cd_user,
            staff_number="ST-1003",
        )

    def test_cd_page_denied_school_directory(self):
        """Strategic Country Director should be denied access to the School Directory route."""
        self.client.force_login(self.cd_user)
        response = self.client.get("/schools")
        # Django require_page_permission decorator redirects unauthorized page entries to /dashboard
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/dashboard"))

    def test_cd_page_denied_planning_dashboard(self):
        """Strategic Country Director should be denied access to the Planning Dashboard route."""
        self.client.force_login(self.cd_user)
        response = self.client.get("/planning")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/dashboard"))

    def test_cceo_access_own_school_drawer_succeeds(self):
        """A CCEO should successfully retrieve their own assigned school details."""
        self.client.force_login(self.cceo1_user)
        response = self.client.get(f"/schools/{self.school_cceo1.id}/edit-drawer")
        self.assertEqual(response.status_code, 200)

    def test_cceo_access_other_cceo_school_drawer_denied(self):
        """A CCEO attempting to access another CCEO's school details drawer should raise PermissionDenied (403 via middleware)."""
        self.client.force_login(self.cceo1_user)
        # Try to load CCEO-2's school edit drawer
        # get_scoped_object_or_404 should throw Django's PermissionDenied, converted to JSON 403 by middleware
        response = self.client.get(f"/schools/{self.school_cceo2.id}/edit-drawer")
        self.assertEqual(response.status_code, 403)

    def test_cd_access_individual_school_denied(self):
        """A Country Director attempting to view/modify a specific school details drawer directly should be blocked by page decorator (302) or HTMX block (403)."""
        self.client.force_login(self.cd_user)
        # Standard request -> redirects
        response = self.client.get(f"/schools/{self.school_cceo1.id}/edit-drawer")
        self.assertEqual(response.status_code, 302)

        # HTMX request -> returns 403 Forbidden
        response_htmx = self.client.get(
            f"/schools/{self.school_cceo1.id}/edit-drawer",
            HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response_htmx.status_code, 403)

    def test_ia_dashboard_redirection_and_blocking(self):
        """Impact Assessment should be redirected to /ia/dashboard/ when accessing /dashboard and blocked from operational views."""
        # Create IA User
        ia_user = User.objects.create_user(
            email="ia@edify.test",
            name="IA Inspector",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="x",
            is_active=True,
        )
        self.client.force_login(ia_user)
        # Entry point redirect
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/ia/dashboard/"))

        # Blocked from normal school directory
        response_schools = self.client.get("/schools")
        self.assertEqual(response_schools.status_code, 302)
        self.assertTrue(response_schools.url.endswith("/dashboard"))

    def test_accountant_dashboard_redirection_and_blocking(self):
        """Program Accountant should be redirected to /accounts when accessing /dashboard and blocked from field planning."""
        accountant_user = User.objects.create_user(
            email="ac@edify.test",
            name="Accountant",
            roles=["Accountant"],
            active_role="Accountant",
            password="x",
            is_active=True,
        )
        self.client.force_login(accountant_user)
        # Entry point redirect
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/accounts"))

        # Blocked from planning
        response_planning = self.client.get("/planning")
        self.assertEqual(response_planning.status_code, 302)
        self.assertTrue(response_planning.url.endswith("/dashboard"))

    def test_rvp_dashboard_rendering_and_blocking(self):
        """Regional Vice President dashboard should render successfully and restrict operational planning access."""
        rvp_user = User.objects.create_user(
            email="rvp@edify.test",
            name="RVP",
            roles=["RegionalVicePresident"],
            active_role="RegionalVicePresident",
            password="x",
            is_active=True,
        )
        self.client.force_login(rvp_user)
        # Dashboard renders
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Regional Executive Dashboard")

        # Blocked from school directory
        response_schools = self.client.get("/schools")
        self.assertEqual(response_schools.status_code, 302)

    def test_hr_dashboard_rendering_and_blocking(self):
        """Human Resources dashboard should render successfully and block access to schools and disbursements."""
        hr_user = User.objects.create_user(
            email="hr@edify.test",
            name="HR Manager",
            roles=["HumanResources"],
            active_role="HumanResources",
            password="x",
            is_active=True,
        )
        self.client.force_login(hr_user)
        # Dashboard renders
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HR & Performance Dashboard")

        # Blocked from school directory
        response_schools = self.client.get("/schools")
        self.assertEqual(response_schools.status_code, 302)

