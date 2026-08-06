"""End-to-end HTTP flow tests for every role journey.

These tests exercise the real request/response cycle (not just services) to
verify the full stack: URL routing -> permission gating -> view -> template ->
context. They catch wiring regressions that unit tests of services miss.

Conventions follow the established house style (see test_role_gating.py):
inline user creation, force_login, hardcoded paths.
"""

from django.test import TestCase, override_settings

from apps.accounts.models import User, StaffProfile, StaffSchoolAssignment
from apps.geography.models import Region, District
from apps.schools.models import School


def _make_geography():
    """Shared geography fixture: one region, one district."""
    region = Region.objects.create(name="East")
    district = District.objects.create(name="Mbale", region=region)
    return region, district


def _make_school(
    region, district, school_id="S-1", name="Test School", school_type="client"
):
    return School.objects.create(
        school_id=school_id,
        name=name,
        region=region,
        district=district,
        enrollment=200,
        school_type=school_type,
    )


def _user(email, role, name=None, password="Test-pass-1!"):
    return User.objects.create_user(
        email=email,
        name=name or email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password=password,
        is_active=True,
    )


# In production, staticfiles use CompressedManifestStaticFilesStorage which
# requires a collected manifest. Tests don't run collectstatic, so override to
# the plain backend on the shared base — full-page renders then resolve
# {% static %} tags without a manifest. All subclasses inherit this override.
@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class BaseFlowTest(TestCase):
    """Shared setUp with geography + a CCEO that owns a school."""

    @classmethod
    def setUpTestData(cls):
        cls.region, cls.district = _make_geography()
        cls.school = _make_school(cls.region, cls.district)

    def _cceo(
        self, email="cceo@flow.test", with_assignment=True, password="Test-pass-1!"
    ):
        u = _user(email, "CCEO", password=password)
        if with_assignment:
            profile = StaffProfile.objects.create(
                user=u, staff_number=f"ST-{email[:3]}"
            )
            StaffSchoolAssignment.objects.create(
                staff=profile, school_id=self.school.id
            )
        return u


class AnonymousAccessFlowTest(BaseFlowTest):
    """Unauthenticated users must be redirected to login; login works."""

    def test_anonymous_dashboard_redirects_to_login_with_next(self):
        r = self.client.get("/dashboard")
        self.assertRedirects(r, "/login?next=/dashboard", fetch_redirect_response=False)

    def test_anonymous_my_plan_redirects_to_login(self):
        r = self.client.get("/my-plan")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r["Location"])

    def test_login_page_renders_for_anonymous(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)

    def test_login_with_valid_credentials_succeeds(self):
        u = self._cceo(password="Secret-1!")
        r = self.client.post("/login", {"email": u.email, "password": "Secret-1!"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/dashboard")

    def test_login_with_wrong_password_fails(self):
        u = self._cceo(password="Secret-1!")
        r = self.client.post("/login", {"email": u.email, "password": "wrong"})
        self.assertEqual(r.status_code, 200)  # re-renders login with error

    def test_login_with_unknown_email_fails(self):
        r = self.client.post(
            "/login", {"email": "nobody@nowhere.test", "password": "x"}
        )
        self.assertEqual(r.status_code, 200)


class CceoJourneyFlowTest(BaseFlowTest):
    """The field officer's primary path: dashboard -> my plan -> planning."""

    def setUp(self):
        super().setUp()
        self.cceo = self._cceo()
        self.client.force_login(self.cceo)

    def test_dashboard_renders_for_cceo(self):
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 200)

    def test_my_plan_renders_for_cceo(self):
        r = self.client.get("/my-plan")
        self.assertEqual(r.status_code, 200)

    def test_planning_renders_for_cceo(self):
        r = self.client.get("/planning")
        self.assertEqual(r.status_code, 200)

    def test_schools_directory_renders_for_cceo(self):
        r = self.client.get("/schools")
        self.assertEqual(r.status_code, 200)

    def test_clusters_renders_for_cceo(self):
        r = self.client.get("/clusters")
        self.assertEqual(r.status_code, 200)

    def test_evidence_center_renders_for_cceo(self):
        r = self.client.get("/evidence/")
        self.assertEqual(r.status_code, 200)

    def test_today_renders_for_cceo(self):
        r = self.client.get("/today")
        self.assertEqual(r.status_code, 200)

    def test_calendar_renders_for_cceo(self):
        r = self.client.get("/calendar")
        self.assertEqual(r.status_code, 200)


class RoleSwitchFlowTest(BaseFlowTest):
    """A user with multiple roles can switch active role."""

    def test_switch_to_held_role_succeeds(self):
        u = User.objects.create_user(
            email="multi@flow.test",
            name="Multi Role",
            roles=["CCEO", "CountryDirector"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        self.client.force_login(u)
        r = self.client.post("/auth/switch-role", {"role": "CountryDirector"})
        self.assertEqual(r.status_code, 302)
        u.refresh_from_db()
        self.assertEqual(u.active_role, "CountryDirector")

    def test_switch_to_unheld_role_rejected(self):
        u = User.objects.create_user(
            email="multi2@flow.test",
            name="Multi Role",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        self.client.force_login(u)
        r = self.client.post("/auth/switch-role", {"role": "CountryDirector"})
        self.assertEqual(r.status_code, 302)
        u.refresh_from_db()
        self.assertEqual(u.active_role, "CCEO")  # unchanged


class AccountantJourneyFlowTest(BaseFlowTest):
    """The Accountant's finance cockpit."""

    def setUp(self):
        super().setUp()
        self.accountant = _user("acct@flow.test", "Accountant")
        self.client.force_login(self.accountant)

    def test_dashboard_redirects_accountant_to_accounts(self):
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/accounts", r["Location"])

    def test_accounts_dashboard_renders(self):
        r = self.client.get("/accounts")
        self.assertEqual(r.status_code, 200)

    def test_fund_allocation_renders_for_accountant(self):
        r = self.client.get("/finance/fund-allocation")
        self.assertEqual(r.status_code, 200)


class ImpactAssessmentJourneyFlowTest(BaseFlowTest):
    """The IA verification queue and dashboard."""

    def setUp(self):
        super().setUp()
        self.ia = _user("ia@flow.test", "ImpactAssessment")
        self.client.force_login(self.ia)

    def test_dashboard_redirects_ia_to_ia_dashboard(self):
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/ia/dashboard/", r["Location"])

    def test_ia_dashboard_renders(self):
        r = self.client.get("/ia/dashboard/")
        self.assertEqual(r.status_code, 200)

    def test_ia_verification_queue_renders(self):
        r = self.client.get("/ia/verification/")
        self.assertEqual(r.status_code, 200)

    def test_ia_history_renders(self):
        r = self.client.get("/ia/history/")
        self.assertEqual(r.status_code, 200)


class ExecutiveJourneyFlowTest(BaseFlowTest):
    """CD / RVP / PL dashboards."""

    def test_country_director_dashboard_renders(self):
        u = _user("cd@flow.test", "CountryDirector")
        self.client.force_login(u)
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 200)

    def test_program_lead_dashboard_renders(self):
        u = _user("pl@flow.test", "Program Lead")
        self.client.force_login(u)
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 200)

    def test_rvp_dashboard_renders(self):
        u = _user("rvp@flow.test", "RegionalVicePresident")
        self.client.force_login(u)
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 200)


class AdminJourneyFlowTest(BaseFlowTest):
    """Admin panel and its sub-pages."""

    def setUp(self):
        super().setUp()
        self.admin = _user("admin@flow.test", "Admin")
        self.client.force_login(self.admin)

    def test_admin_panel_renders(self):
        r = self.client.get("/admin-panel")
        self.assertEqual(r.status_code, 200)

    def test_admin_users_renders(self):
        r = self.client.get("/admin-panel/users")
        self.assertEqual(r.status_code, 200)

    def test_admin_roles_permissions_renders(self):
        r = self.client.get("/admin-panel/roles-permissions")
        self.assertEqual(r.status_code, 200)


class HealthCheckFlowTest(TestCase):
    """The /api/health endpoint Railway probes."""

    def test_health_endpoint_returns_200(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)


class HtmxPartialFlowTest(BaseFlowTest):
    """HTMX partials respond correctly and respect the HX-Request header."""

    def setUp(self):
        super().setUp()
        self.cceo = self._cceo()
        self.client.force_login(self.cceo)

    def test_my_plan_htmx_returns_partial(self):
        r = self.client.get("/my-plan", HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)

    def test_schools_htmx_returns_partial(self):
        r = self.client.get("/schools", HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)
