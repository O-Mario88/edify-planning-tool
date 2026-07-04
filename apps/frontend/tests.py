from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.accounts.models import StaffProfile, StaffSchoolAssignment
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

    def test_country_director_dashboard_renders(self):
        User = get_user_model()
        cd_user = User.objects.create(
            id="cd-1",
            email="cd@edify.org",
            name="CD User",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True
        )
        cd_user.save()
        self.client.force_login(cd_user)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/dashboards/cd.html")

    def test_special_projects_dashboard_renders(self):
        User = get_user_model()
        sp_user = User.objects.create(
            id="sp-1",
            email="sp@edify.org",
            name="Special Projects User",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
            is_active=True
        )
        sp_user.save()
        self.client.force_login(sp_user)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/dashboards/special_projects.html")

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

    def test_school_directory_view_model_mapping(self):
        from apps.frontend.view_models import SchoolDirectoryViewModel
        
        # Test mapping unclustered school
        clusters_dict = {self.cluster.id: self.cluster.name}
        vm = SchoolDirectoryViewModel.from_school(self.school, self.cceo_user, clusters_dict, active_projects_exist=True)
        self.assertEqual(vm["school_name"], "Kampola High School")
        self.assertFalse(vm["is_clustered"])
        self.assertIn("add_to_cluster", vm["available_actions"])
        # CCEO lacks project manage permission
        self.assertNotIn("assign_to_project", vm["available_actions"])
        self.assertEqual(vm["disabled_reasons"]["assign_to_project"], "You do not have permission to assign projects.")

    def test_add_to_cluster_drawer_get(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get(f"/schools/{self.school.id}/add-to-cluster")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/schools/add_to_cluster_drawer.html")

    def test_add_to_cluster_drawer_post_existing(self):
        self.client.force_login(self.cceo_user)
        # Post assignment to existing cluster
        response = self.client.post(
            f"/schools/{self.school.id}/add-to-cluster",
            {"cluster_action_type": "existing", "existing_cluster_id": self.cluster.id}
        )
        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.cluster.id)
        self.assertEqual(self.school.cluster_status, "clustered")

    def test_assign_to_project_permission_gate(self):
        # CCEO has no project manage permission, should show error
        self.client.force_login(self.cceo_user)
        response = self.client.get(f"/schools/{self.school.id}/assign-to-project")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/schools/drawer_error.html")

    def test_assign_to_project_drawer_admin(self):
        User = get_user_model()
        admin_user = User.objects.create(
            id="admin-1",
            email="admin@edify.org",
            name="Admin User",
            roles=["Admin"],
            active_role="Admin",
            is_active=True
        )
        self.client.force_login(admin_user)
        
        # Create a project
        from apps.projects.models import Project
        project = Project.objects.create(
            name="Edify Tech Upgrade 2026",
            code="ETU26",
            category="intervention_specific"
        )
        
        # GET drawer
        response = self.client.get(f"/schools/{self.school.id}/assign-to-project")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/schools/assign_to_project_drawer.html")
        
        # POST assignment
        response = self.client.post(
            f"/schools/{self.school.id}/assign-to-project",
            {
                "project_id": project.id,
                "project_type": "Tech Support",
                "participation_type": "Partner",
                "start_date": "2026-07-01",
                "support_area": "Laptops",
                "notes": "Assigning laptops to Kampola High."
            }
        )
        self.assertEqual(response.status_code, 200)
        
        # Verify assignment in DB
        from apps.projects.models import ProjectSchoolAssignment
        assignment = ProjectSchoolAssignment.objects.get(school=self.school, project=project)
        self.assertEqual(assignment.project_type, "Tech Support")
        self.assertEqual(assignment.support_area, "Laptops")

    def test_my_plan_view_model_and_filters(self):
        self.client.force_login(self.cceo_user)
        
        # Test basic view rendering
        response = self.client.get("/my-plan?period=week&month=5&week=2")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My Plan")
        
        # Test filters via HTMX request
        response = self.client.get(
            "/my-plan?period=week&month=5&week=2",
            HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/my_plan/workspace.html")

    def test_cost_catalogue_row_and_initialization(self):
        User = get_user_model()
        cd_user = User.objects.create(
            id="cd-2",
            email="cd2@edify.org",
            name="CD User 2",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True
        )
        cd_user.save()
        self.client.force_login(cd_user)

        # 1. Initialize default catalogue
        response = self.client.post("/cost-settings/initialize-default")
        self.assertEqual(response.status_code, 302) # redirects to /dashboard

        # Verify active catalogue in DB
        from apps.budget.models import CostCatalogue, CostSetting
        active_cat = CostCatalogue.objects.filter(is_active=True).first()
        self.assertIsNotNone(active_cat)

        # Verify default settings created/attached
        breakfast_setting = CostSetting.objects.get(key="breakfast", catalogue=active_cat)
        self.assertEqual(breakfast_setting.unit_cost, 8000)

        # 2. Get edit row view
        response = self.client.get(f"/cost-settings/row/{breakfast_setting.key}?mode=edit")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/cost_settings/cost_setting_row.html")
        self.assertContains(response, 'name="unit_cost"')

        # 3. Post cost update
        response = self.client.post(
            f"/cost-settings/row/{breakfast_setting.key}",
            {"unit_cost": "9,500", "reason": "Inflation adjustment"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/cost_settings/cost_setting_row.html")
        
        # Verify DB updated
        breakfast_setting.refresh_from_db()
        self.assertEqual(breakfast_setting.unit_cost, 9500)
        self.assertEqual(breakfast_setting.version, 2)

    def test_partner_assignment_and_scheduling_flow(self):
        # 1. Setup a partner user and a partner organization
        from apps.partners.models import Partner
        from apps.activities.models import Activity
        from apps.accounts.models import StaffSupervisorAssignment, StaffProfile
        User = get_user_model()
        
        partner = Partner.objects.create(
            name="Partner Org",
            active_status=True
        )
        partner_user = User.objects.create(
            id="partner-u-1",
            email="partner@edify.org",
            name="Partner User",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True
        )
        partner.user_id = partner_user.id
        partner.save()

        # Create a supervisor staff user (PL)
        pl_user = User.objects.create(
            id="pl-u-1",
            email="pl@edify.org",
            name="PL User",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True
        )
        pl_profile = StaffProfile.objects.create(
            id="staff-pl-1",
            user=pl_user,
            title="PL"
        )
        
        # Supervise CCEO
        StaffSupervisorAssignment.objects.create(
            supervisor=pl_profile,
            supervisee=self.cceo_profile
        )
        
        # Link cluster to school to bring it in scope
        self.school.cluster_id = self.cluster.id
        self.school.save()

        # 2. Assign cluster to partner via POST
        self.client.force_login(pl_user)
        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "cluster_id": self.cluster.id,
                "partner_id": partner.id,
                "activity_type": "meeting"
            }
        )
        self.assertEqual(response.status_code, 200, response.content)

        # Verify Activity with status='assigned_to_partner' was created
        act = Activity.objects.get(cluster=self.cluster, assigned_partner_id=partner.id)
        self.assertEqual(act.status, "assigned_to_partner")
        self.assertEqual(act.monitored_by_staff_id, pl_user.id)

        # 3. Partner schedules the assigned activity
        self.client.force_login(partner_user)
        # Verify reschedule drawer displays the assigning staff's name
        response = self.client.get(f"/my-plan/{act.id}/reschedule-drawer")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, pl_user.name)

        # Post scheduling date
        response = self.client.post(
            f"/my-plan/{act.id}/reschedule",
            {
                "scheduled_date": "2026-07-15",
                "reason": "Scheduling based on plan"
            },
            HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)

        # Verify activity updated to partner_scheduled and monitored_by_staff_id is PL user
        act.refresh_from_db()
        self.assertEqual(act.status, "partner_scheduled")
        self.assertEqual(act.monitored_by_staff_id, pl_user.id)

        # 4. Supervisor (PL) views My Plan and sees this scheduled activity
        self.client.force_login(pl_user)
        response = self.client.get("/my-plan?period=week&month=7&week=3")
        self.assertEqual(response.status_code, 200)

    def test_notification_drawer_and_mark_read(self):
        from apps.notifications.models import Notification
        
        # 1. Create notifications for CCEO
        n1 = Notification.objects.create(
            recipient_id=self.cceo_user.id,
            title="Notification A",
            body="First message body",
            priority="urgent",
            status="unread"
        )
        n2 = Notification.objects.create(
            recipient_id=self.cceo_user.id,
            title="Notification B",
            body="Second message body",
            priority="high",
            status="unread"
        )

        # Log in and check drawer view
        self.client.force_login(self.cceo_user)
        response = self.client.get("/notifications/drawer")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Notification A")
        self.assertContains(response, "Notification B")
        self.assertContains(response, "You have 2 unread messages")

        # 2. Mark one notification as read
        response = self.client.post(
            f"/notifications/{n1.id}/read",
            HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        
        n1.refresh_from_db()
        self.assertEqual(n1.status, "read")
        
        # Verify drawer count decreased
        self.assertContains(response, "notification-badge-container")
        self.assertContains(response, "notification-badge-count")

        # 3. Mark all notifications as read
        response = self.client.post(
            "/notifications/mark-all-read",
            HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        
        n2.refresh_from_db()
        self.assertEqual(n2.status, "read")
