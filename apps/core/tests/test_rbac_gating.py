from django.test import TestCase, Client
from apps.accounts.models import User
from apps.core.rbac import EdifyRole
from apps.activities.models import Activity
from apps.schools.models import School
from apps.geography.models import District, Region
from apps.core.exceptions import BadRequest, Forbidden
from apps.messaging import services as messaging_services

class RbacGatingTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Create users with different roles
        self.cceo_user = User.objects.create_user(
            email="cceo@edify.org",
            password="password123",
            name="CCEO Test User",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
        )
        
        self.accountant_user = User.objects.create_user(
            email="accountant@edify.org",
            password="password123",
            name="Accountant Test User",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
        )
        
        self.partner_user = User.objects.create_user(
            email="partner@edify.org",
            password="password123",
            name="Partner Test User",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
        )

        self.rvp_user = User.objects.create_user(
            email="rvp@edify.org",
            password="password123",
            name="RVP Test User",
            roles=[EdifyRole.REGIONAL_VICE_PRESIDENT.value],
            active_role=EdifyRole.REGIONAL_VICE_PRESIDENT.value,
        )

        self.hr_user = User.objects.create_user(
            email="hr@edify.org",
            password="password123",
            name="HR Test User",
            roles=[EdifyRole.HUMAN_RESOURCES.value],
            active_role=EdifyRole.HUMAN_RESOURCES.value,
        )

        # Create Region and District records
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Central Kampala", region=self.region)
        self.school = School.objects.create(
            school_id="SCH-999",
            name="Kampala Progressive School",
            district=self.district,
            region=self.region,
            planning_readiness="ready"
        )
        from apps.accounts.models import StaffProfile, StaffSchoolAssignment
        self.cceo_profile = StaffProfile.objects.create(
            user=self.cceo_user,
            staff_number="ST-CCEO-99"
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_profile,
            school_id=self.school.id
        )
        self.activity = Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="scheduled",
            responsible_staff_id=self.cceo_user.id
        )

    def test_unauthenticated_redirect_with_next_param(self):
        """Unauthenticated requests must redirect to login with next parameter."""
        response = self.client.get("/planning")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=/planning", response.url)

    def test_cceo_restricted_access(self):
        """CCEO must be redirected when accessing restricted admin or finance views."""
        self.client.force_login(self.cceo_user)
        
        # Attempt to access Admin Dashboard
        response = self.client.get("/admin-panel")
        self.assertEqual(response.status_code, 302)  # Redirects back to dashboard
        self.assertIn("/dashboard", response.url)
        
        # Attempt to access Accountant Disbursements
        response = self.client.get("/disbursements")
        self.assertEqual(response.status_code, 302)  # Redirects back to dashboard
        self.assertIn("/dashboard", response.url)

    def test_accountant_restricted_access(self):
        """Accountants must be blocked from scheduling or planning actions."""
        self.client.force_login(self.accountant_user)
        
        # Attempt to access planning workspace / scheduling dashboard
        response = self.client.get("/planning")
        self.assertEqual(response.status_code, 302)  # Redirects to dashboard
        self.assertIn("/dashboard", response.url)
        
        # Attempt to open scheduling modal (direct GET/POST checks)
        response = self.client.get("/planning/schedule-modal?school_id=" + str(self.school.id))
        self.assertEqual(response.status_code, 302)  # Redirects to dashboard
        self.assertIn("/dashboard", response.url)

    def test_partner_restricted_access(self):
        """Partner cannot access broad staff directory, admin panel or other private views."""
        self.client.force_login(self.partner_user)
        
        # Attempt to access staff directory
        response = self.client.get("/staff")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard", response.url)
        
        # Attempt to access PL review queue
        response = self.client.get("/pl/review-queue")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard", response.url)

    def test_activity_mutation_ownership_gating(self):
        """Users cannot reschedule or edit activities they do not own or supervise."""
        self.client.force_login(self.partner_user)
        
        # Attempt to reschedule CCEO's activity
        response = self.client.post(f"/my-plan/{self.activity.id}/reschedule", {
            "scheduled_date": "2026-08-15",
            "reason": "Intruder attempt"
        })
        self.assertEqual(response.status_code, 403)  # Forbidden

    def test_message_requires_context(self):
        """All new messages must fail validation if contextType or contextId are missing."""
        data = {
            "recipientId": self.cceo_user.id,
            "subject": "Missing Context Test",
            "body": "This message has no context parameters."
        }
        with self.assertRaises(BadRequest):
            messaging_services.send(data, self.partner_user)

    def test_partner_cannot_message_rvp_or_hr(self):
        """Enforces recipient rules: Partners cannot send messages to RVPs or HR."""
        # 1. Partner to RVP
        data_rvp = {
            "recipientId": self.rvp_user.id,
            "subject": "Hello RVP",
            "body": "Should be blocked.",
            "contextType": "school",
            "contextId": self.school.id
        }
        with self.assertRaises(Forbidden):
            messaging_services.send(data_rvp, self.partner_user)

        # 2. Partner to HR
        data_hr = {
            "recipientId": self.hr_user.id,
            "subject": "Hello HR",
            "body": "Should be blocked.",
            "contextType": "school",
            "contextId": self.school.id
        }
        with self.assertRaises(Forbidden):
            messaging_services.send(data_hr, self.partner_user)

    def test_rvp_hr_cannot_message_partner(self):
        """Enforces recipient rules: RVPs/HR have no partner message access."""
        # 1. RVP to Partner
        data_rvp = {
            "recipientId": self.partner_user.id,
            "subject": "Hello Partner",
            "body": "Should be blocked.",
            "contextType": "school",
            "contextId": self.school.id
        }
        with self.assertRaises(Forbidden):
            messaging_services.send(data_rvp, self.rvp_user)

        # 2. HR to Partner
        data_hr = {
            "recipientId": self.partner_user.id,
            "subject": "Hello Partner",
            "body": "Should be blocked.",
            "contextType": "school",
            "contextId": self.school.id
        }
        with self.assertRaises(Forbidden):
            messaging_services.send(data_hr, self.hr_user)

    def test_reply_inherits_context(self):
        """Replies must automatically inherit context from parent thread context settings."""
        # Create thread & message from CCEO to Accountant
        data = {
            "recipientId": self.accountant_user.id,
            "subject": "Budget discussion",
            "body": "Please review this budget line.",
            "contextType": "budget_line",
            "contextId": "BL-445"
        }
        msg = messaging_services.send(data, self.cceo_user)
        thread_id = msg["threadId"]

        # Reply from Accountant
        reply_data = {
            "body": "Budget line approved."
        }
        reply_msg = messaging_services.send(reply_data, self.accountant_user) if False else messaging_services.reply(thread_id, reply_data, self.accountant_user)

        # Assert inherited context
        self.assertEqual(reply_msg["contextType"], "budget_line")
        self.assertEqual(reply_msg["contextId"], "BL-445")

    def test_schedule_modal_views(self):
        """Test scheduling modal views for school and cluster under CCEO."""
        from apps.clusters.models import Cluster
        self.client.force_login(self.cceo_user)
        
        # Test school schedule modal
        response = self.client.get(f"/planning/schedule-modal?school_id={self.school.id}")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/planning/schedule_drawer.html")
        
        # Create a cluster
        cluster = Cluster.objects.create(name="Central Cluster", district=self.district, region=self.region)
        self.school.cluster_id = cluster.id
        self.school.save()
        
        # Test cluster schedule modal
        response = self.client.get(f"/planning/schedule-modal?cluster_id={cluster.id}&action=training")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/planning/schedule_cluster_drawer.html")

    def test_partner_onboarding_rbac(self):
        """Verify that only Admin, CD, or IA can onboard partners, and others are blocked."""
        from apps.partners import services as partner_services
        from apps.accounts.models import User
        from apps.core.rbac import EdifyRole
        from apps.core.exceptions import Forbidden

        admin_user = User.objects.create_user(
            email="admin.onboard@edify.org",
            password="password123",
            name="Admin User",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
        )
        cd_user = User.objects.create_user(
            email="cd.onboard@edify.org",
            password="password123",
            name="CD User",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
        )
        ia_user = User.objects.create_user(
            email="ia.onboard@edify.org",
            password="password123",
            name="IA User",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
        )

        data = {"name": "Test Partner Role Check"}

        # Admin must succeed
        partner_admin = partner_services.onboard(data, admin_user)
        self.assertEqual(partner_admin["name"], "Test Partner Role Check")

        # CD must succeed
        data["name"] = "CD Test Partner"
        partner_cd = partner_services.onboard(data, cd_user)
        self.assertEqual(partner_cd["name"], "CD Test Partner")

        # IA must succeed
        data["name"] = "IA Test Partner"
        partner_ia = partner_services.onboard(data, ia_user)
        self.assertEqual(partner_ia["name"], "IA Test Partner")

        # Other roles (e.g., CCEO, Accountant) must be blocked
        with self.assertRaises(Forbidden):
            partner_services.onboard({"name": "Blocked Partner 1"}, self.cceo_user)

        with self.assertRaises(Forbidden):
            partner_services.onboard({"name": "Blocked Partner 2"}, self.accountant_user)
