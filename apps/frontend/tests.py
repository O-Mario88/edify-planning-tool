from datetime import date

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
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
            is_active=True,
        )
        self.cceo_user.set_password("pass123")
        self.cceo_user.save()

        # Create StaffProfile for CCEO
        self.cceo_profile = StaffProfile.objects.create(
            id="staff-cceo-1", user=self.cceo_user, title="CCEO"
        )

        # Create basic geography
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampola", region=self.region)
        self.sub_county = SubCounty.objects.create(
            name="Central Subcounty", district=self.district
        )

        # Create a school
        self.school = School.objects.create(
            school_id="SCH-99",
            name="Kampola High School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            current_fy_ssa_status="not_done",
            planning_readiness="locked",
        )

        # Assign CCEO to the school so it is in scope
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_profile, school_id=self.school.id
        )

        # Create a cluster
        self.cluster = Cluster.objects.create(
            name="Central Cluster One",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active",
        )

    def _publish_test_catalogue(self, scheduled_date: str):
        """Provide the CD-owned catalogue required by costed schedule tests."""
        from apps.budget.models import CostCatalogue
        from apps.core.fy import get_operational_fy

        return CostCatalogue.objects.get_or_create(
            fy=get_operational_fy(date.fromisoformat(scheduled_date)),
            version=1,
            defaults={"label": "Frontend workflow test catalogue"},
        )[0]

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
        self.assertContains(response, "Schools Needing Urgent Attention")
        self.assertContains(response, "Schedule Baseline SSA Visit")
        self.assertContains(response, "Assign to Partner")

    def test_program_lead_dashboard_renders_successfully(self):
        User = get_user_model()
        pl_user = User.objects.create(
            id="pl-dashboard-1",
            email="pl-dashboard@edify.org",
            name="PL Dashboard User",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )
        pl_profile = StaffProfile.objects.create(
            id="staff-pl-dashboard-1", user=pl_user, title="Program Lead"
        )
        from apps.accounts.models import StaffSupervisorAssignment

        StaffSupervisorAssignment.objects.create(
            supervisor=pl_profile, supervisee=self.cceo_profile
        )

        self.client.force_login(pl_user)
        for url in ("/dashboard", "/dashboard/pl"):
            response = self.client.get(url)

            self.assertEqual(response.status_code, 200, url)
            self.assertTemplateUsed(response, "pages/dashboards/pl.html")
            self.assertContains(response, "Program Lead Dashboard")

    def test_urgent_action_prefills_the_real_scheduling_drawer(self):
        self.client.force_login(self.cceo_user)
        self.school.current_fy_ssa_status = "done"
        self.school.save(update_fields=["current_fy_ssa_status", "updated_at"])
        response = self.client.get(
            f"/planning/schedule-modal?school_id={self.school.id}"
            "&recommended_activity_type=coaching_visit"
            "&focus_intervention=teaching_environment",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Schedule Coaching Visit")
        self.assertContains(
            response,
            'option value="coaching_visit" selected',
            html=False,
        )
        self.assertContains(
            response,
            'value="teaching_environment" selected',
            html=False,
        )

    def test_country_director_dashboard_renders(self):
        User = get_user_model()
        cd_user = User.objects.create(
            id="cd-1",
            email="cd@edify.org",
            name="CD User",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
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
            is_active=True,
        )
        sp_user.save()
        self.client.force_login(sp_user)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/dashboards/special_projects.html")

    def test_partner_roles_redirect_to_partner_scoped_dashboard(self):
        """PartnerAdmin/PartnerFieldOfficer logins previously fell through to
        the generic internal-staff dashboard (pages/dashboards/main.html) —
        which shows school/cluster/team-target panels that make no sense for
        a Partner org login with no StaffProfile or country/cluster scope.
        /dashboard must send them to the existing partner-scoped landing page
        instead."""
        User = get_user_model()
        for idx, role in enumerate(("PartnerAdmin", "PartnerFieldOfficer")):
            with self.subTest(role=role):
                partner_user = User.objects.create(
                    id=f"partner-role-{idx}",
                    email=f"{role.lower()}@edify.org",
                    name=f"{role} User",
                    roles=[role],
                    active_role=role,
                    is_active=True,
                )
                self.client.force_login(partner_user)
                response = self.client.get("/dashboard")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, "/partner/today")

    def test_main_dashboard_recommended_action_is_honest(self):
        """The fallback dashboard's 'Next Recommended Action' card must never
        show a hardcoded suggestion — it should be None (honest empty state)
        when there is nothing real to act on, and reflect a real pending
        fund request when one exists, matching the same count already shown
        in Attention Needed."""
        from apps.fund_requests.models import WeeklyFundRequest
        from apps.core.fy import get_operational_fy
        from datetime import date, timedelta

        User = get_user_model()
        admin_user = User.objects.create(
            id="admin-reco-1",
            email="admin-reco@edify.org",
            name="Admin User",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        self.client.force_login(admin_user)

        # setUp() creates self.school with current_fy_ssa_status="not_done",
        # so with nothing else pending the honest recommendation is the real
        # SSA gap -- not a hardcoded suggestion, and not silence either.
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/dashboards/main.html")
        reco = response.context["recommended_action"]
        self.assertIsNotNone(reco)
        self.assertEqual(reco["cta_href"], "/ssa")
        self.assertIn("1 school", reco["detail"])
        self.assertNotContains(response, "Confirm this week")

        html = response.content.decode()
        self.assertEqual(html.count('class="admin-kpi"'), 7)
        for region in (
            "admin-workspace",
            "admin-grid--top",
            "admin-grid--middle",
            "admin-grid--lower",
            "admin-rail",
        ):
            self.assertIn(region, html)

        # Close the SSA gap -> genuinely nothing to act on -> honest empty
        # state, never a fabricated fallback suggestion.
        self.school.current_fy_ssa_status = "done"
        self.school.save(update_fields=["current_fy_ssa_status"])
        response = self.client.get("/dashboard")
        self.assertIsNone(response.context["recommended_action"])
        self.assertContains(response, "Nothing needs action right now.")

        # A real pending fund request -> recommended_action reflects it.
        week_start = date.today() - timedelta(days=date.today().weekday())
        WeeklyFundRequest.objects.create(
            fy=get_operational_fy(),
            week_start_date=week_start,
            week_end_date=week_start + timedelta(days=6),
            responsible_user=admin_user.id,
            status="submitted_to_pl",
            total_amount=100000,
        )
        response = self.client.get("/dashboard")
        reco = response.context["recommended_action"]
        self.assertIsNotNone(reco)
        self.assertEqual(reco["cta_href"], "/fund-requests/weekly")
        self.assertIn("1 weekly fund request", reco["detail"])

    def test_schools_directory_view_renders(self):
        from apps.projects.models import Project

        self.school.shipping_address = "Plot 12, Kampala Road"
        self.school.account_owner_id = self.cceo_profile.id
        self.school.save(update_fields=["shipping_address", "account_owner_id"])
        Project.objects.create(
            name="School Directory Action Project",
            code="SDAP-26",
            category="intervention_specific",
        )
        self.client.force_login(self.cceo_user)
        response = self.client.get("/schools")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/schools/index.html")
        self.assertContains(
            response, 'class="school-directory-list school-record-list"'
        )
        self.assertContains(response, 'class="school-directory-row school-record-row"')
        self.assertContains(response, 'x-data="{ openSchoolId: null }"')
        self.assertContains(response, '@click.outside="openSchoolId = null"')
        self.assertContains(response, "openSchoolId ===")
        self.assertContains(response, "Kampola High School")
        self.assertContains(response, "Not assessed")
        self.assertContains(response, "Visit:")
        self.assertContains(response, "Training:")
        self.assertContains(response, "Not assigned")
        self.assertContains(response, "Plot 12, Kampala Road")
        self.assertContains(response, "School Type:")
        self.assertContains(response, "Staff Name:")
        self.assertContains(response, self.cceo_user.name)
        self.assertContains(response, "Add to Cluster")
        self.assertContains(response, "Add to Project")
        self.assertNotContains(response, "Schedule Now")
        self.assertContains(response, f"/schools/{self.school.id}/add-to-cluster")
        self.assertContains(response, f"/schools/{self.school.id}/assign-to-project")
        self.assertNotContains(response, "Column Settings")

    def test_school_lists_show_real_grouped_ssa_scores(self):
        """Both school lists must show the stored scores, never placeholders."""
        from apps.core.fy import get_operational_fy
        from apps.ssa.models import SsaRecord, SsaScore

        record = SsaRecord.objects.create(
            school=self.school,
            fy=get_operational_fy(),
            quarter="Q1",
            date_of_ssa=timezone.now(),
            verification_status="confirmed",
            uploaded_by=self.cceo_user.id,
        )
        for intervention, score in (
            ("exposure_to_word_of_god", 3.0),
            ("learning_environment", 1.0),
            ("financial_health", 4.0),
            ("leadership", 7.0),
            ("christlike_behaviour", 8.0),
            ("teaching_environment", 8.5),
            ("government_requirement", 6.0),
            ("enrolment", 6.0),
        ):
            SsaScore.objects.create(
                ssa_record=record, intervention=intervention, score=score
            )

        self.client.force_login(self.cceo_user)
        for url in ("/schools", "/planning"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response, "SSA interventions needing urgent attention"
                )
                self.assertContains(response, "SSA interventions performing well")
                self.assertContains(response, "SSA interventions to watch")
                self.assertContains(response, "Exposure to the Word of God")
                self.assertContains(response, "(3/10)")
                self.assertContains(response, "Teacher&#x27;s Environment")
                self.assertContains(response, "(8.5/10)")

        planning_school = next(
            item for item in response.context["schools"] if item["id"] == self.school.id
        )
        self.assertEqual(planning_school["ssaAverage"], 5.4)

    def test_planning_keeps_partner_assignment_available_when_scheduling_is_blocked(
        self,
    ):
        """A partner handoff does not create a costed activity until dated.

        The Planning list must therefore keep Assign available to authorised
        staff even if the school's own staff scheduling is blocked by setup
        readiness checks such as an unassigned cluster or missing catalogue.
        """
        self.client.force_login(self.cceo_user)

        response = self.client.get("/planning")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'hx-get="/planning/assign-partner-modal?school_id={self.school.school_id}"',
        )

    def test_school_directory_tabs_and_page_size_are_server_owned(self):
        """Tab clicks must send one canonical value and every later filter
        request must retain it. Page size is a real backend filter, not a
        decorative selector."""
        self.school.cluster_status = "clustered"
        self.school.cluster_id = self.cluster.id
        self.school.save(update_fields=["cluster_status", "cluster_id"])
        self.client.force_login(self.cceo_user)

        response = self.client.get(
            "/schools",
            {"tab": "clustered", "per_page": "25"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="schools-table-container",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/schools/htmx_response.html")
        self.assertEqual(response.context["active_tab"], "clustered")
        self.assertEqual(response.context["per_page"], 25)
        self.assertEqual(response.context["page_obj"].paginator.per_page, 25)
        self.assertContains(
            response,
            'id="schools-tab-clustered"',
        )
        self.assertContains(response, 'aria-selected="true"')
        self.assertContains(response, 'id="filters-tab-input"')
        self.assertContains(response, 'value="clustered"')

        invalid = self.client.get("/schools", {"tab": "invented"})
        self.assertEqual(invalid.context["active_tab"], "all")

    def test_school_directory_excel_export_is_a_real_workbook(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get("/schools", {"export": "xlsx"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("schools_export.xlsx", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"PK"))

    def test_school_detail_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get(f"/schools/{self.school.school_id}")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/schools/detail.html")

    def test_clusters_directory_view_renders(self):
        self.cluster.cluster_leader_name = "Jane Leader"
        self.cluster.cluster_leader_phone = "+256 700 123456"
        self.cluster.save(update_fields=["cluster_leader_name", "cluster_leader_phone"])
        self.client.force_login(self.cceo_user)
        response = self.client.get("/clusters")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/clusters/index.html")
        self.assertContains(response, "Cluster Leader:")
        self.assertContains(response, "Jane Leader")
        self.assertContains(response, "Cluster Leader Phone:")
        self.assertContains(response, "+256 700 123456")

    def test_cluster_directory_groups_actual_intervention_scores(self):
        """Cluster cards present confirmed aggregate SSA scores as recommendations."""
        from apps.core.fy import get_operational_fy
        from apps.ssa.models import SsaRecord, SsaScore

        self.school.cluster_id = self.cluster.id
        self.school.cluster_status = "clustered"
        self.school.save(update_fields=["cluster_id", "cluster_status"])
        ssa = SsaRecord.objects.create(
            school=self.school,
            fy=get_operational_fy(),
            quarter="Q4",
            date_of_ssa=timezone.now(),
            verification_status="confirmed",
            uploaded_by=self.cceo_user.id,
        )
        for intervention, score in (
            ("leadership", 3.0),
            ("financial_health", 7.0),
            ("learning_environment", 6.0),
        ):
            SsaScore.objects.create(
                ssa_record=ssa,
                intervention=intervention,
                score=score,
            )

        self.client.force_login(self.cceo_user)
        response = self.client.get("/clusters")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SSA interventions needing urgent attention")
        self.assertContains(response, "SSA interventions performing well")
        self.assertContains(response, "SSA interventions to watch")
        self.assertContains(response, "(3/10)")
        self.assertContains(response, "(7/10)")
        self.assertContains(response, "(6/10)")
        self.assertContains(response, "Schedule")
        self.assertContains(
            response,
            'class="school-record-action school-record-action--assign"',
        )
        self.assertNotContains(response, "Cluster Intervention Scores")

        cluster_card = next(
            item
            for item in response.context["clusters"]
            if item["id"] == self.cluster.id
        )
        self.assertTrue(cluster_card["has_ssa_scores"])
        self.assertEqual(
            [item["code"] for item in cluster_card["ssa_groups"][0]["items"]],
            ["leadership"],
        )

    def test_cluster_detail_view_renders(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get(f"/clusters/{self.cluster.id}")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/clusters/detail.html")

    def test_planning_dashboard_view_renders(self):
        from django.utils import timezone
        from apps.core.fy import get_operational_fy
        from apps.ssa.models import SsaRecord, SsaScore

        self.school.cluster_id = self.cluster.id
        self.school.cluster_status = "clustered"
        self.school.account_owner_id = self.cceo_profile.id
        self.school.current_fy_ssa_status = "done"
        self.school.shipping_address = "Plot 12, Kampala Road"
        self.school.save()

        ssa = SsaRecord.objects.create(
            school=self.school,
            fy=get_operational_fy(),
            quarter="Q4",
            date_of_ssa=timezone.now(),
            verification_status="confirmed",
            uploaded_by=self.cceo_user.id,
        )
        for intervention, score in (
            ("leadership", 3.5),
            ("financial_health", 4.5),
            ("learning_environment", 5.5),
            ("christlike_behaviour", 8.0),
        ):
            SsaScore.objects.create(
                ssa_record=ssa,
                intervention=intervention,
                score=score,
            )

        self.client.force_login(self.cceo_user)
        response = self.client.get("/planning")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/planning/index.html")
        self.assertTemplateUsed(response, "partials/planning/school_row.html")
        self.assertContains(response, 'class="planning-school-list school-record-list"')
        self.assertContains(response, 'x-data="{ openSchoolId: null }"')
        self.assertContains(response, '@click.outside="openSchoolId = null"')
        self.assertContains(response, "SSA interventions needing urgent attention")
        self.assertContains(response, "(3.5/10)")
        self.assertContains(response, self.cluster.name)
        self.assertContains(response, "Plot 12, Kampala Road")
        self.assertContains(response, "School Type:")
        self.assertContains(response, "Staff Name:")
        self.assertContains(response, self.cceo_user.name)
        self.assertContains(response, "Schedule")
        self.assertContains(response, ">Assign<")

        school_row = next(
            item for item in response.context["schools"] if item["id"] == self.school.id
        )
        self.assertEqual(
            [item["code"] for item in school_row["weakestInterventions"]],
            ["leadership", "financial_health", "learning_environment"],
        )
        self.assertEqual(school_row["ssaAverage"], 5.4)

    def test_cluster_school_list_uses_shared_clickable_school_records(self):
        self.school.cluster_id = self.cluster.id
        self.school.cluster_status = "clustered"
        self.school.shipping_address = "Plot 12, Kampala Road"
        self.school.save(
            update_fields=["cluster_id", "cluster_status", "shipping_address"]
        )
        self.client.force_login(self.cceo_user)

        response = self.client.get(f"/partials/clusters/{self.cluster.id}/schools")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="cluster-school-list school-record-list"')
        self.assertContains(response, 'class="school-record-row__expander"')
        self.assertContains(response, 'x-data="{ openSchoolId: null }"')
        self.assertContains(response, '@click.outside="openSchoolId = null"')
        self.assertContains(response, "Plot 12, Kampala Road")
        self.assertContains(response, "School Type:")
        self.assertContains(response, "Schedule")
        self.assertContains(response, ">Assign<")

    def test_planning_filters_return_one_table_and_refresh_tab_state(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get(
            "/planning",
            {"tab": "core", "q": "Kampola"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="schools-table-container",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/planning/school_table.html")
        self.assertEqual(response.context["active_tab"], "core")
        self.assertContains(response, 'id="schools-table-container"', count=1)
        self.assertContains(response, 'id="planning-tabs-header"')
        self.assertContains(response, 'hx-swap-oob="outerHTML"')
        self.assertContains(response, 'id="planning-tab-core"')
        self.assertContains(response, 'aria-selected="true"')

    def test_schedule_form_action_param_selects_training(self):
        # Regression: templates/pages/trainings/index.html links to
        # /planning/schedule?action=training (view reads "action", not
        # "type") — must resolve to the training form, not silently fall
        # back to the "visit" default.
        self.client.force_login(self.cceo_user)
        response = self.client.get("/planning/schedule?action=training")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["action"], "training")

    def test_schedule_form_school_param_preselects_school(self):
        # Regression: templates/partials/clusters/cluster_schools_table.html
        # links to /planning/schedule?action=visit&school=<schoolId> (view
        # reads "school", not "school_id") — must resolve selected_school.
        self.client.force_login(self.cceo_user)
        response = self.client.get(
            f"/planning/schedule?action=visit&school={self.school.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["selected_school"])
        self.assertEqual(response.context["selected_school"].id, self.school.id)

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
        admin_user = get_user_model().objects.create(
            id="admin-health-1",
            email="admin-health@edify.org",
            name="Admin Health User",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        admin_user.set_password("pass123")
        admin_user.save()
        self.client.force_login(admin_user)
        response = self.client.get("/system-health")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/system_health/index.html")

    def test_school_directory_view_model_mapping(self):
        from apps.frontend.view_models import SchoolDirectoryViewModel

        # Test mapping unclustered school
        clusters_dict = {self.cluster.id: self.cluster.name}
        vm = SchoolDirectoryViewModel.from_school(
            self.school, self.cceo_user, clusters_dict, active_projects_exist=True
        )
        self.assertEqual(vm["school_name"], "Kampola High School")
        self.assertFalse(vm["is_clustered"])
        self.assertIn("add_to_cluster", vm["available_actions"])
        # CCEO works the operational school directory, including project assignment.
        self.assertIn("assign_to_project", vm["available_actions"])
        self.assertNotIn("assign_to_project", vm["disabled_reasons"])

    def test_add_to_cluster_drawer_get(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get(f"/schools/{self.school.id}/add-to-cluster")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/schools/add_to_cluster_drawer.html")

    def test_create_cluster_drawer_uses_guided_geography_workflow(self):
        outside_region = Region.objects.create(name="Outside Drawer Region")
        outside_district = District.objects.create(
            name="Outside Drawer District", region=outside_region
        )
        SubCounty.objects.create(
            name="Outside Drawer Subcounty", district=outside_district
        )

        self.client.force_login(self.cceo_user)
        response = self.client.get("/clusters/create-drawer")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "partials/clusters/create_cluster_drawer.html"
        )
        self.assertContains(response, 'class="cluster-create-drawer"')
        self.assertContains(response, 'class="cluster-create-basics"')
        self.assertContains(response, 'name="district_id"')
        self.assertContains(response, 'name="sub_county_ids"')
        self.assertContains(response, 'name="cluster_leader_name"')
        self.assertContains(response, 'name="cluster_leader_phone"')
        self.assertContains(response, "school-record-action--assign")
        self.assertContains(response, "school-record-action--schedule")
        self.assertContains(response, "Create cluster")
        self.assertNotContains(response, "Assigned Staff")
        self.assertNotContains(response, "Outside Drawer District")
        self.assertNotContains(response, "Outside Drawer Subcounty")

    def test_cluster_name_must_be_unique_within_district(self):
        from apps.clusters.services import create_cluster
        from apps.core.exceptions import BadRequest

        with self.assertRaisesMessage(
            BadRequest, "A cluster with this name already exists in this district."
        ):
            create_cluster(
                {
                    "name": self.cluster.name.lower(),
                    "regionId": self.region.id,
                    "districtId": self.district.id,
                    "subCountyIds": [],
                },
                self.cceo_user,
            )

    def test_add_to_cluster_drawer_post_existing(self):
        self.client.force_login(self.cceo_user)
        # Post assignment to existing cluster
        response = self.client.post(
            f"/schools/{self.school.id}/add-to-cluster",
            {"cluster_action_type": "existing", "existing_cluster_id": self.cluster.id},
        )
        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.cluster.id)
        self.assertEqual(self.school.cluster_status, "clustered")

    def test_assign_to_project_permission_gate(self):
        # Accountant is finance-only and has no school_directory page access at
        # all (a stricter, page-level gate than project.assignSchool), so it's
        # redirected before ever reaching the drawer view.
        User = get_user_model()
        accountant_user = User.objects.create(
            id="accountant-1",
            email="accountant@edify.org",
            name="Accountant User",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        self.client.force_login(accountant_user)
        response = self.client.get(f"/schools/{self.school.id}/assign-to-project")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard")

    def test_assign_to_project_drawer_cceo(self):
        # CCEO works the operational school directory, including project assignment.
        self.client.force_login(self.cceo_user)

        from apps.projects.models import Project

        project = Project.objects.create(
            name="Edify Tech Upgrade 2026",
            code="ETU26",
            category="intervention_specific",
        )

        response = self.client.get(f"/schools/{self.school.id}/assign-to-project")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "partials/schools/assign_to_project_drawer.html"
        )

    def test_assign_to_project_drawer_admin(self):
        User = get_user_model()
        admin_user = User.objects.create(
            id="admin-1",
            email="admin@edify.org",
            name="Admin User",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        self.client.force_login(admin_user)

        # Create a project
        from apps.projects.models import Project

        project = Project.objects.create(
            name="Edify Tech Upgrade 2026",
            code="ETU26",
            category="intervention_specific",
        )

        # GET drawer
        response = self.client.get(f"/schools/{self.school.id}/assign-to-project")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "partials/schools/assign_to_project_drawer.html"
        )

        # POST assignment
        response = self.client.post(
            f"/schools/{self.school.id}/assign-to-project",
            {
                "project_id": project.id,
                "project_type": "Tech Support",
                "participation_type": "Partner",
                "start_date": "2026-07-01",
                "support_area": "Laptops",
                "notes": "Assigning laptops to Kampola High.",
            },
        )
        self.assertEqual(response.status_code, 200)

        # Verify assignment in DB
        from apps.projects.models import ProjectSchoolAssignment

        assignment = ProjectSchoolAssignment.objects.get(
            school=self.school, project=project
        )
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
            "/my-plan?period=week&month=5&week=2", HTTP_HX_REQUEST="true"
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
            is_active=True,
        )
        cd_user.save()
        self.client.force_login(cd_user)

        # 1. Initialize default catalogue
        response = self.client.post("/cost-settings/initialize-default")
        self.assertEqual(response.status_code, 302)  # redirects to /dashboard

        # Verify active catalogue in DB
        from apps.budget.models import CostCatalogue, CostSetting

        active_cat = CostCatalogue.objects.filter(is_active=True).first()
        self.assertIsNotNone(active_cat)

        # Verify default settings created/attached
        breakfast_setting = CostSetting.objects.get(
            key="breakfast", catalogue=active_cat
        )
        self.assertEqual(breakfast_setting.unit_cost, 8000)

        # 2. Get edit row view
        response = self.client.get(
            f"/cost-settings/row/{breakfast_setting.key}?mode=edit"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "partials/cost_settings/cost_setting_row.html"
        )
        self.assertContains(response, 'name="unit_cost"')

        # 3. Post cost update
        response = self.client.post(
            f"/cost-settings/row/{breakfast_setting.key}",
            {"unit_cost": "9,500", "reason": "Inflation adjustment"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "partials/cost_settings/cost_setting_row.html"
        )

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

        partner = Partner.objects.create(name="Partner Org", active_status=True)
        partner_user = User.objects.create(
            id="partner-u-1",
            email="partner@edify.org",
            name="Partner User",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True,
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
            is_active=True,
        )
        pl_profile = StaffProfile.objects.create(
            id="staff-pl-1", user=pl_user, title="PL"
        )

        # Supervise CCEO
        StaffSupervisorAssignment.objects.create(
            supervisor=pl_profile, supervisee=self.cceo_profile
        )

        # Link cluster to school to bring it in scope
        self.school.cluster_id = self.cluster.id
        self.school.save()

        # 2. Assign cluster to partner via POST — no target date yet, so this
        # only records the handoff (PartnerAssignment); the Activity itself
        # is correctly deferred to schedule-time (activities.services.
        # partner_schedule's own documented contract, same as Core Schools'
        # assign -> schedule flow) instead of persisting an un-costed
        # activity via raw ORM writes.
        from apps.partners.models import PartnerAssignment

        self.client.force_login(pl_user)
        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "cluster_id": self.cluster.id,
                "partner_id": partner.id,
                "activity_type": "meeting",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)

        pa = PartnerAssignment.objects.get(cluster=self.cluster, partner=partner)
        self.assertEqual(pa.status, "pending_scheduling")
        self.assertFalse(
            Activity.objects.filter(
                cluster=self.cluster, assigned_partner_id=partner.id
            ).exists()
        )

        # 2b. Partner later picks a date — apps.activities.services.
        # partner_schedule lazily creates the Activity off the
        # PartnerAssignment at that point (the same funnel Core Schools uses
        # for its own assign -> schedule flow).
        from apps.activities.services import partner_schedule

        scheduled = partner_schedule(
            pa.id, {"scheduledDate": "2026-07-14"}, partner_user
        )
        self.assertEqual(scheduled["status"], "partner_scheduled")
        act = Activity.objects.get(id=scheduled["id"])
        self.assertEqual(act.assigned_partner_id, partner.id)

        # 3. Partner reschedules the activity to a new date
        self.client.force_login(partner_user)
        # Verify reschedule drawer displays the assigning staff's name
        response = self.client.get(f"/my-plan/{act.id}/reschedule-drawer")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, pl_user.name)

        # Post scheduling date
        response = self.client.post(
            f"/my-plan/{act.id}/reschedule",
            {"scheduled_date": "2026-07-15", "reason": "Scheduling based on plan"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)

        # Verify activity updated to partner_scheduled and retains the
        # canonical StaffProfile monitor identity used by My Plan scoping.
        act.refresh_from_db()
        self.assertEqual(act.status, "partner_scheduled")
        self.assertEqual(act.monitored_by_staff_id, pl_profile.id)

        # 4. Supervisor (PL) views My Plan and sees this scheduled activity
        self.client.force_login(pl_user)
        response = self.client.get("/my-plan?period=week&month=7&week=3")
        self.assertEqual(response.status_code, 200)

    def test_partner_portal_pages_scope_to_own_partner_activities(self):
        """The four Partner Portal pages (today/schools/activities/evidence)
        must scope Activity by assigned_partner_id via resolve_partner_ids(),
        not by responsible_staff_id=user.id. A Partner login has no
        StaffProfile, so responsible_staff_id (a StaffProfile id) can never
        equal user.id (a User id) — that comparison silently matched nothing,
        rendering all four pages structurally empty for every real partner
        login. This also guards against the opposite failure: leaking another
        partner's activities/schools/evidence into view."""
        from apps.partners.models import Partner
        from apps.activities.models import Activity
        from apps.evidence.models import EvidenceRecord
        from datetime import date, timedelta

        User = get_user_model()
        today = date.today()

        # A real partner login: Partner linked via Partner.user, NO
        # StaffProfile — this is the actual shape of a partner field-officer
        # login (see apps/core/scoping.py::resolve_partner_ids).
        partner = Partner.objects.create(name="Own Partner Org", active_status=True)
        partner_user = User.objects.create(
            id="partner-own-1",
            email="partner-own@edify.org",
            name="Own Partner User",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True,
        )
        partner.user = partner_user
        partner.save()

        other_partner = Partner.objects.create(
            name="Other Partner Org", active_status=True
        )
        other_school = School.objects.create(
            school_id="SCH-OTHER-1",
            name="Other Partner School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
        )

        own_today = Activity.objects.create(
            school=self.school,
            delivery_type="partner",
            assigned_partner_id=partner.id,
            activity_type="school_visit",
            status="scheduled",
            planned_date=today,
        )
        own_upcoming = Activity.objects.create(
            school=self.school,
            delivery_type="partner",
            assigned_partner_id=partner.id,
            activity_type="school_visit",
            status="scheduled",
            planned_date=today + timedelta(days=3),
        )
        own_completed_no_evidence = Activity.objects.create(
            school=self.school,
            delivery_type="partner",
            assigned_partner_id=partner.id,
            activity_type="school_visit",
            status="completed",
            planned_date=today - timedelta(days=1),
        )
        EvidenceRecord.objects.create(
            activity_id=own_today.id,
            uploaded_by=partner_user.id,
            kind="photo",
            uri="own-evidence.jpg",
            original_name="own-evidence.jpg",
            file_size=1024,
        )

        # Same-day / same-shape records for a DIFFERENT partner — must never
        # appear on partner_user's pages.
        other_today = Activity.objects.create(
            school=other_school,
            delivery_type="partner",
            assigned_partner_id=other_partner.id,
            activity_type="school_visit",
            status="scheduled",
            planned_date=today,
        )
        other_completed_no_evidence = Activity.objects.create(
            school=other_school,
            delivery_type="partner",
            assigned_partner_id=other_partner.id,
            activity_type="school_visit",
            status="completed",
            planned_date=today - timedelta(days=1),
        )

        self.client.force_login(partner_user)

        # /partner/today — own today + upcoming visible, other partner's not.
        response = self.client.get("/partner/today")
        self.assertEqual(response.status_code, 200)
        today_ids = {a.id for a in response.context["today_activities"]}
        upcoming_ids = {a.id for a in response.context["upcoming"]}
        self.assertEqual(today_ids, {own_today.id})
        self.assertEqual(upcoming_ids, {own_upcoming.id})
        self.assertNotIn(other_today.id, today_ids)

        # /partner/schools — own school listed, other partner's school is not.
        response = self.client.get("/partner/schools")
        self.assertEqual(response.status_code, 200)
        school_ids = {s.id for s in response.context["schools"]}
        self.assertEqual(school_ids, {self.school.id})
        self.assertNotIn(other_school.id, school_ids)

        # /partner/activities — only own three activities listed.
        response = self.client.get("/partner/activities")
        self.assertEqual(response.status_code, 200)
        activity_ids = {a.id for a in response.context["activities"]}
        self.assertEqual(
            activity_ids, {own_today.id, own_upcoming.id, own_completed_no_evidence.id}
        )

        # /partner/evidence — own evidence + own pending-evidence activity;
        # the other partner's completed-no-evidence activity must not leak in.
        response = self.client.get("/partner/evidence")
        self.assertEqual(response.status_code, 200)
        evidence_activity_ids = {e.activity_id for e in response.context["evidence"]}
        pending_ids = {a.id for a in response.context["pending"]}
        self.assertEqual(evidence_activity_ids, {own_today.id})
        self.assertEqual(pending_ids, {own_completed_no_evidence.id})
        self.assertNotIn(other_completed_no_evidence.id, pending_ids)

    def test_partners_list_and_detail_scope_partner_role_to_own_org(self):
        """/partners and /partners/<id> apply no row-level scoping in
        navigation (ALL_ROLES), unlike the REST endpoint which requires
        PARTNER_VIEW/PARTNER_MANAGE — permissions Partner roles don't hold.
        A partner-org login must only ever see/browse into its OWN partner's
        directory row and detail page, never another partner's."""
        from apps.partners.models import Partner

        User = get_user_model()
        partner = Partner.objects.create(name="Own Partner Org", active_status=True)
        partner_user = User.objects.create(
            id="partner-scope-1",
            email="partner-scope@edify.org",
            name="Scoped Partner User",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True,
        )
        partner.user = partner_user
        partner.save()

        other_partner = Partner.objects.create(
            name="Other Partner Org", active_status=True
        )

        self.client.force_login(partner_user)

        # Directory listing — only the partner's own org appears.
        response = self.client.get("/partners")
        self.assertEqual(response.status_code, 200)
        listed_ids = {p.id for p in response.context["partners"]}
        self.assertEqual(listed_ids, {partner.id})
        self.assertNotIn(other_partner.id, listed_ids)

        # Own detail page is reachable.
        response = self.client.get(f"/partners/{partner.id}")
        self.assertEqual(response.status_code, 200)

        # Another partner's detail page must be blocked, not just hidden from
        # the directory — this is the browser-route path the audit flagged.
        response = self.client.get(f"/partners/{other_partner.id}")
        self.assertEqual(response.status_code, 403)

    # ── assign_partner_action_view / bulk_action_view now converge on the
    # SAME validated + costed creation funnel (activities.services.create /
    # partner_schedule) instead of writing PartnerAssignment/Activity via raw
    # ORM. ──────────────────────────────────────────────────────────────────
    def test_assign_partner_action_with_date_creates_activity_and_cost_snapshot(self):
        """Single-item assign, with a target date already chosen, must create
        BOTH the PartnerAssignment (handoff record) and a real, gated, costed
        Activity in one atomic step, instead of a raw ORM Activity write with
        no cost data at all."""
        from apps.partners.models import Partner, PartnerAssignment
        from apps.activities.models import Activity, ActivityScheduleCostLine
        from apps.budget.models import CostSetting

        self._publish_test_catalogue("2026-07-20")
        CostSetting.objects.get_or_create(
            key="partner_visit_lump_sum",
            defaults={"label": "Partner Visit", "unit_cost": 35000},
        )[0]
        partner = Partner.objects.create(name="Gate Partner", active_status=True)

        self.client.force_login(self.cceo_user)
        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "school_id": self.school.school_id,
                "partner_id": partner.id,
                "activity_type": "school_visit",
                "purpose": "Follow-up on enrolment drive",
                "expected_date": "2026-07-20",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)

        pa = PartnerAssignment.objects.get(school=self.school, partner=partner)
        self.assertEqual(pa.status, "partner_scheduled")

        act = Activity.objects.get(school=self.school, assigned_partner_id=partner.id)
        self.assertEqual(act.delivery_type, "partner")
        self.assertIsNotNone(act.scheduled_date)
        # Real cost snapshot — the whole point of routing through
        # activities.services.create() instead of a bare ORM write.
        self.assertGreater(act.est_cost_cents, 0)
        self.assertFalse(act.cost_missing)
        self.assertTrue(ActivityScheduleCostLine.objects.filter(activity=act).exists())

    def test_assign_partner_action_double_submit_does_not_duplicate(self):
        """A double-click or a retried htmx POST for the same handoff must
        not create a second PartnerAssignment or a second costed Activity —
        the money only exists once."""
        from apps.partners.models import Partner, PartnerAssignment
        from apps.activities.models import Activity
        from apps.budget.models import CostSetting

        self._publish_test_catalogue("2026-07-20")
        CostSetting.objects.get_or_create(
            key="partner_visit_lump_sum",
            defaults={"label": "Partner Visit", "unit_cost": 35000},
        )[0]
        partner = Partner.objects.create(
            name="Double Click Partner", active_status=True
        )

        self.client.force_login(self.cceo_user)
        payload = {
            "school_id": self.school.school_id,
            "partner_id": partner.id,
            "activity_type": "school_visit",
            "purpose": "Follow-up on enrolment drive",
            "expected_date": "2026-07-20",
        }
        r1 = self.client.post("/planning/assign-partner-action", payload)
        r2 = self.client.post("/planning/assign-partner-action", payload)
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertEqual(r2.status_code, 200, r2.content)

        self.assertEqual(
            PartnerAssignment.objects.filter(
                school=self.school, partner=partner
            ).count(),
            1,
        )
        self.assertEqual(
            Activity.objects.filter(
                school=self.school, assigned_partner_id=partner.id
            ).count(),
            1,
        )

    def test_assign_partner_action_without_date_defers_activity_creation(self):
        """No target date at assign time -> only the PartnerAssignment handoff
        record is written; Activity creation is correctly deferred to
        schedule-time (activities.services.partner_schedule's own documented
        contract, same as Core Schools' assign -> schedule flow) instead of
        an un-costed Activity being created via raw ORM."""
        from apps.partners.models import Partner, PartnerAssignment
        from apps.activities.models import Activity

        partner = Partner.objects.create(name="Deferred Partner", active_status=True)

        self.client.force_login(self.cceo_user)
        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "school_id": self.school.school_id,
                "partner_id": partner.id,
                "activity_type": "school_visit",
                "purpose": "Follow-up on enrolment drive",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)

        pa = PartnerAssignment.objects.get(school=self.school, partner=partner)
        self.assertEqual(pa.status, "pending_scheduling")
        self.assertFalse(
            Activity.objects.filter(
                school=self.school, assigned_partner_id=partner.id
            ).exists()
        )

    def test_assign_partner_action_saves_when_no_cost_rate_is_configured(self):
        """A missing rate flags the snapshot but never blocks scheduling."""
        from apps.partners.models import Partner, PartnerAssignment
        from apps.activities.models import Activity

        partner = Partner.objects.create(name="Unpriced Partner", active_status=True)

        self.client.force_login(self.cceo_user)
        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "school_id": self.school.school_id,
                "partner_id": partner.id,
                "activity_type": "school_visit",
                "purpose": "Follow-up visit",
                "expected_date": "2026-07-20",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(
            PartnerAssignment.objects.filter(
                school=self.school, partner=partner
            ).exists()
        )
        activity = Activity.objects.get(
            school=self.school, assigned_partner_id=partner.id
        )
        self.assertTrue(activity.cost_missing)
        self.assertGreater(activity.schedule_cost_lines.count(), 0)

    def test_assign_partner_action_allows_an_ssa_non_recommended_focus(self):
        """SSA recommendations guide the work but do not block it."""
        from apps.partners.models import Partner, PartnerAssignment
        from apps.activities.models import Activity
        from apps.budget.models import CostSetting
        from apps.ssa.models import SsaRecord, SsaScore

        CostSetting.objects.get_or_create(
            key="partner_visit_lump_sum",
            defaults={"label": "Partner Visit", "unit_cost": 35000},
        )[0]
        ssa = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=timezone.make_aware(timezone.datetime(2026, 6, 1)),
            fy="2026",
            quarter="Q4",
            verification_status="confirmed",
        )
        for intervention, score in [
            ("teaching_environment", 9),
            ("financial_health", 6),
            ("christlike_behaviour", 8),
            ("exposure_to_word_of_god", 7),
            ("government_requirement", 5),
            ("leadership", 6),
            ("enrolment", 4),
            ("learning_environment", 7),
        ]:
            SsaScore.objects.create(
                ssa_record=ssa, intervention=intervention, score=score
            )

        partner = Partner.objects.create(name="SSA Gate Partner", active_status=True)

        self.client.force_login(self.cceo_user)
        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "school_id": self.school.school_id,
                "partner_id": partner.id,
                "activity_type": "school_visit",
                "purpose": "Teaching environment follow-up",
                "focus_intervention": "teaching_environment",
                "expected_date": "2026-07-20",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(
            PartnerAssignment.objects.filter(
                school=self.school, partner=partner
            ).exists()
        )
        self.assertTrue(
            Activity.objects.filter(
                school=self.school, assigned_partner_id=partner.id
            ).exists()
        )

    def test_bulk_assign_partner_with_date_creates_activities(self):
        """Bulk partner assignment with a shared date must create BOTH the
        PartnerAssignment and a real, costed Activity per school — visible on
        the partner's My Plan feed and the assigning staff's Partner
        Monitoring bucket — instead of the PartnerAssignment-only write that
        left both feeds blind to the handoff (the HIGH finding)."""
        from apps.partners.models import Partner, PartnerAssignment
        from apps.activities.models import Activity
        from apps.budget.models import CostSetting
        from apps.schools.models import School
        from apps.accounts.models import StaffSchoolAssignment

        self._publish_test_catalogue("2026-07-21")
        CostSetting.objects.get_or_create(
            key="partner_visit_lump_sum",
            defaults={"label": "Partner Visit", "unit_cost": 35000},
        )[0]
        partner = Partner.objects.create(name="Bulk Dated Partner", active_status=True)
        second_school = School.objects.create(
            school_id="SCH-100",
            name="Second School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_profile, school_id=second_school.id
        )

        self.client.force_login(self.cceo_user)
        response = self.client.post(
            "/planning/bulk-action",
            {
                "action": "partner",
                "school_ids": [self.school.school_id, second_school.school_id],
                "partner_id": partner.id,
                "scheduled_date": "2026-07-21",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)

        for school in (self.school, second_school):
            pa = PartnerAssignment.objects.get(school=school, partner=partner)
            self.assertEqual(pa.status, "partner_scheduled")
            act = Activity.objects.get(school=school, assigned_partner_id=partner.id)
            self.assertEqual(act.delivery_type, "partner")
            self.assertGreater(act.est_cost_cents, 0)
            self.assertFalse(act.cost_missing)

    def test_bulk_assign_partner_without_date_defers_activity_creation(self):
        """Bulk partner assignment with no date yet must only write the
        PartnerAssignment handoff records. This is the exact HIGH finding:
        previously NO Activity was EVER created for bulk assignment, so the
        handoff was invisible everywhere. It now correctly defers to
        schedule-time instead of silently losing the work item forever."""
        from apps.partners.models import Partner, PartnerAssignment
        from apps.activities.models import Activity

        partner = Partner.objects.create(
            name="Bulk Deferred Partner", active_status=True
        )

        self.client.force_login(self.cceo_user)
        response = self.client.post(
            "/planning/bulk-action",
            {
                "action": "partner",
                "school_ids": [self.school.school_id],
                "partner_id": partner.id,
            },
        )
        self.assertEqual(response.status_code, 200, response.content)

        pa = PartnerAssignment.objects.get(school=self.school, partner=partner)
        self.assertEqual(pa.status, "pending_scheduling")
        self.assertEqual(pa.expected_activity_type, "school_visit")
        self.assertFalse(
            Activity.objects.filter(
                school=self.school, assigned_partner_id=partner.id
            ).exists()
        )

    def test_bulk_assign_partner_without_partner_id_returns_clean_error(self):
        """The bulk toolbar's 'Assign Partner' button used to submit with no
        partner_id at all, which get_object_or_404 turned into an unhandled
        404 that hx-target="body" swapped over the ENTIRE planning page.
        Missing partner_id must now surface a clean, in-place 400 error."""
        self.client.force_login(self.cceo_user)
        response = self.client.post(
            "/planning/bulk-action",
            {"action": "partner", "school_ids": [self.school.school_id]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Select a partner", response.content)

    def test_bulk_assign_partner_double_submit_does_not_duplicate(self):
        """A double-click on 'Confirm Handoff' must not create a second
        PartnerAssignment/Activity per school."""
        from apps.partners.models import Partner, PartnerAssignment
        from apps.activities.models import Activity
        from apps.budget.models import CostSetting

        self._publish_test_catalogue("2026-07-21")
        CostSetting.objects.get_or_create(
            key="partner_visit_lump_sum",
            defaults={"label": "Partner Visit", "unit_cost": 35000},
        )[0]
        partner = Partner.objects.create(
            name="Bulk Double Click Partner", active_status=True
        )

        self.client.force_login(self.cceo_user)
        payload = {
            "action": "partner",
            "school_ids": [self.school.school_id],
            "partner_id": partner.id,
            "scheduled_date": "2026-07-21",
        }
        r1 = self.client.post("/planning/bulk-action", payload)
        r2 = self.client.post("/planning/bulk-action", payload)
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(
            PartnerAssignment.objects.filter(
                school=self.school, partner=partner
            ).count(),
            1,
        )
        self.assertEqual(
            Activity.objects.filter(
                school=self.school, assigned_partner_id=partner.id
            ).count(),
            1,
        )

    def test_bulk_assign_partner_saves_when_no_cost_rate_is_configured(self):
        """Bulk scheduling also records an unpriced snapshot instead of blocking."""
        from apps.partners.models import Partner, PartnerAssignment
        from apps.activities.models import Activity

        partner = Partner.objects.create(
            name="Bulk Unpriced Partner", active_status=True
        )

        self.client.force_login(self.cceo_user)
        response = self.client.post(
            "/planning/bulk-action",
            {
                "action": "partner",
                "school_ids": [self.school.school_id],
                "partner_id": partner.id,
                "scheduled_date": "2026-07-21",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(
            PartnerAssignment.objects.filter(
                school=self.school, partner=partner
            ).exists()
        )
        activity = Activity.objects.get(
            school=self.school, assigned_partner_id=partner.id
        )
        self.assertTrue(activity.cost_missing)

    def test_assign_partner_action_cluster_uses_default_participant_costing(self):
        """Cluster scheduling uses a sensible default when no count is supplied."""
        from apps.partners.models import Partner, PartnerAssignment
        from apps.activities.models import Activity
        from apps.budget.models import CostSetting

        CostSetting.objects.get_or_create(
            key="partner_cluster_activity_rate",
            defaults={"label": "Partner cluster activity rate", "unit_cost": 40000},
        )[0]
        self.school.cluster_id = self.cluster.id
        self.school.save()
        partner = Partner.objects.create(
            name="Cluster Gate Partner", active_status=True
        )

        self.client.force_login(self.cceo_user)
        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "cluster_id": self.cluster.id,
                "partner_id": partner.id,
                "activity_type": "meeting",
                "expected_date": "2026-07-20",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(
            PartnerAssignment.objects.filter(
                cluster=self.cluster, partner=partner
            ).exists()
        )
        self.assertTrue(
            Activity.objects.filter(
                cluster=self.cluster, assigned_partner_id=partner.id
            ).exists()
        )

    def test_notification_drawer_and_mark_read(self):
        from apps.notifications.models import Notification

        # 1. Create notifications for CCEO
        n1 = Notification.objects.create(
            recipient_id=self.cceo_user.id,
            title="Notification A",
            body="First message body",
            priority="urgent",
            status="unread",
        )
        n2 = Notification.objects.create(
            recipient_id=self.cceo_user.id,
            title="Notification B",
            body="Second message body",
            priority="high",
            status="unread",
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
            f"/notifications/{n1.id}/read", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)

        n1.refresh_from_db()
        self.assertEqual(n1.status, "read")

        # Verify drawer count decreased
        self.assertContains(response, "notification-badge-container")
        self.assertContains(response, "notification-badge-count")

        # 3. Mark all notifications as read
        response = self.client.post(
            "/notifications/mark-all-read", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)

        n2.refresh_from_db()
        self.assertEqual(n2.status, "read")

    def test_visits_log_evidence_badge_uses_real_evidence_status_values(self):
        """/visits used to compare evidence_status against 'submitted' and
        'verified' — neither exists in apps.core.enums.EvidenceStatus
        (none/uploaded/accepted/returned/rejected), so every visit showed
        the evidence column as missing/blank regardless of actual state."""
        from apps.activities.models import Activity
        from django.utils import timezone

        with_evidence = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_visit",
            status="completed",
            evidence_status="uploaded",
            responsible_staff_id=self.cceo_user.id,
            planned_date=timezone.now().date(),
        )
        without_evidence = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_visit",
            status="completed",
            evidence_status="none",
            responsible_staff_id=self.cceo_user.id,
            planned_date=timezone.now().date(),
        )

        self.client.force_login(self.cceo_user)
        response = self.client.get("/visits")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Submitted")
        self.assertContains(response, "Missing")

        # And an accepted (IA-approved) evidence state also renders as
        # submitted, not blank.
        with_evidence.evidence_status = "accepted"
        with_evidence.save(update_fields=["evidence_status"])
        without_evidence.delete()
        response = self.client.get("/visits")
        self.assertContains(response, "Submitted")
        self.assertNotContains(response, "Missing")


class GlobalSearchAndMapScopingTests(TestCase):
    """Regression tests for the global /search page and /map view:

    1. Search results are scope-constrained — a CCEO never sees schools
       outside their assigned portfolio.
    2. An activity-only match renders an Activities section instead of the
       historical blank page (has_results was True but the template had no
       activities block, so neither results nor "No results" rendered).
    3. Every authenticated role can open /search (the topbar renders the
       search box for all roles) — no Access-Denied bounce.
    4. The map plots only in-scope schools.
    """

    def setUp(self):
        User = get_user_model()
        self.cceo_user = User.objects.create(
            id="search-cceo-1",
            email="search-cceo@edify.org",
            name="Search CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.cceo_profile = StaffProfile.objects.create(
            id="staff-search-cceo-1", user=self.cceo_user, title="CCEO"
        )

        self.region = Region.objects.create(name="Search Region")
        self.district = District.objects.create(
            name="Search District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Search Subcounty", district=self.district
        )

        self.in_scope_school = School.objects.create(
            school_id="SCH-SRCH-1",
            name="Scopetest Alpha School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            current_fy_ssa_status="not_done",
            planning_readiness="locked",
            latitude=0.35,
            longitude=32.58,
        )
        self.out_of_scope_school = School.objects.create(
            school_id="SCH-SRCH-2",
            name="Scopetest Beta School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            current_fy_ssa_status="not_done",
            planning_readiness="locked",
            latitude=0.36,
            longitude=32.59,
        )
        # Only Alpha is in the CCEO's portfolio.
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_profile, school_id=self.in_scope_school.id
        )

    def test_search_scopes_schools_to_user_portfolio(self):
        """A CCEO's search must exclude schools outside their assignment."""
        self.client.force_login(self.cceo_user)
        response = self.client.get("/search", {"q": "Scopetest"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scopetest Alpha School")
        self.assertNotContains(response, "Scopetest Beta School")

    def test_search_activity_only_match_renders_activity_results(self):
        """An activity-only hit renders the Activities section — not the
        historical blank page (no results AND no 'No results found')."""
        from apps.activities.models import Activity

        cluster = Cluster.objects.create(
            name="Zebrafield Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active",
        )
        Activity.objects.create(
            cluster=cluster,
            activity_type="cluster_meeting",
            status="scheduled",
            delivery_type="staff",
            responsible_staff_id=self.cceo_profile.id,
        )

        self.client.force_login(self.cceo_user)
        response = self.client.get("/search", {"q": "Zebrafield"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Activities")
        self.assertContains(response, "Zebrafield Cluster")
        self.assertNotContains(response, "No results found")

    def test_search_page_accessible_to_every_role(self):
        """Every authenticated role reaches /search (200 — no 403, no
        Access-Denied 302 to /dashboard), with and without a query."""
        User = get_user_model()
        roles = [
            "CCEO",
            "ProgramLead",
            "CountryDirector",
            "ImpactAssessment",
            "RegionalVicePresident",
            "HumanResources",
            "Accountant",
            "ProjectCoordinator",
            "PartnerAdmin",
            "Admin",
        ]
        for i, role in enumerate(roles):
            user = User.objects.create(
                id=f"search-role-{i}",
                email=f"search-role-{i}@edify.org",
                name=f"Search {role}",
                roles=[role],
                active_role=role,
                is_active=True,
            )
            self.client.force_login(user)
            response = self.client.get("/search")
            self.assertEqual(
                response.status_code, 200, msg=f"{role} blocked from /search"
            )
            self.assertTemplateUsed(response, "pages/search/index.html")
            # Scope resolution must not crash for any role.
            response = self.client.get("/search", {"q": "Scopetest"})
            self.assertEqual(
                response.status_code, 200, msg=f"{role} search with query failed"
            )

    def test_map_scopes_schools_to_user_portfolio(self):
        """The map plots only in-scope schools for a role-scoped user."""
        self.client.force_login(self.cceo_user)
        response = self.client.get("/map")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scopetest Alpha School")
        self.assertNotContains(response, "Scopetest Beta School")


class DataQualityCenterActionTests(TestCase):
    """Data Quality Center used to be entirely read-only: DataQualityIssue.status
    /resolved_at/assigned_to were defined on the model but nothing ever wrote
    them. These tests cover the resolve/assign POST action added to close
    that gap."""

    def setUp(self):
        from apps.schools.models import DataQualityIssue

        User = get_user_model()
        self.admin_user = User.objects.create(
            id="dq-admin-1",
            email="dq-admin@edify.org",
            name="DQ Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )

        self.region = Region.objects.create(name="DQ Region")
        self.district = District.objects.create(name="DQ District", region=self.region)
        self.sub_county = SubCounty.objects.create(
            name="DQ Subcounty", district=self.district
        )
        self.school = School.objects.create(
            school_id="SCH-DQ-1",
            name="DQ Test School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            current_fy_ssa_status="not_done",
            planning_readiness="locked",
        )
        # School.save() auto-generates issues via create_data_quality_issues();
        # grab the "missing_phone" one it produces (the school has no phone).
        self.issue = DataQualityIssue.objects.filter(
            school=self.school, issue_type="missing_phone", status="open"
        ).first()
        self.assertIsNotNone(
            self.issue, "expected School.save() to auto-create a missing_phone issue"
        )

    def test_resolve_action_writes_status_and_resolved_at(self):
        from apps.audit.models import AuditLog

        self.client.force_login(self.admin_user)
        response = self.client.post(
            f"/data-quality/issue/{self.issue.id}/action", {"action": "resolve"}
        )
        self.assertEqual(response.status_code, 200)

        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, "resolved")
        self.assertIsNotNone(self.issue.resolved_at)
        self.assertEqual(self.issue.assigned_to, str(self.admin_user.id))
        self.assertContains(response, "Resolved")

        self.assertTrue(
            AuditLog.objects.filter(
                action="data_quality_issue.resolve", subject_id=self.issue.id
            ).exists(),
            "resolving a data quality issue must write an audit log entry",
        )

    def test_assign_action_writes_assigned_to_without_resolving(self):
        from apps.audit.models import AuditLog

        self.client.force_login(self.admin_user)
        response = self.client.post(
            f"/data-quality/issue/{self.issue.id}/action", {"action": "assign"}
        )
        self.assertEqual(response.status_code, 200)

        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, "open")
        self.assertEqual(self.issue.assigned_to, str(self.admin_user.id))
        self.assertContains(response, "Assigned")

        self.assertTrue(
            AuditLog.objects.filter(
                action="data_quality_issue.assign", subject_id=self.issue.id
            ).exists(),
            "assigning a data quality issue must write an audit log entry",
        )

    def test_data_quality_center_renders_open_issue_with_resolve_button(self):
        """The page must actually surface open issues (it used to build the
        querysets in the view but never render them)."""
        self.client.force_login(self.admin_user)
        response = self.client.get("/admin-panel/data-quality-center")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DQ Test School")
        self.assertContains(response, f"/data-quality/issue/{self.issue.id}/action")


class SchoolDirectoryQueryCountTest(TestCase):
    """Regression test for the school directory N+1 (Phase 3 perf audit).

    SchoolDirectoryViewModel.from_school() used to run ~5-7 per-school
    queries (SSA exists, visit exists/count, training exists/count, cluster
    training count) for every row on the page. The query count therefore
    scaled linearly with the number of schools on the page. It must now be
    flat regardless of how many schools are on the page, because
    school_directory_view batches those lookups once via
    SchoolDirectoryViewModel.bulk_progress().
    """

    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create(
            id="admin-perf-1",
            email="admin-perf@edify.org",
            name="Admin Perf User",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        self.admin_user.set_password("pass123")
        self.admin_user.save()

        self.region = Region.objects.create(name="Perf Region")
        self.district = District.objects.create(
            name="Perf District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Perf Subcounty", district=self.district
        )

        from apps.activities.models import Activity
        from apps.ssa.models import SsaRecord
        from django.utils import timezone

        self.schools = []
        for i in range(12):
            school = School.objects.create(
                school_id=f"PERF-{i}",
                name=f"Perf School {i}",
                region=self.region,
                district=self.district,
                sub_county=self.sub_county,
                school_type="core" if i % 2 == 0 else "client",
                current_fy_ssa_status="not_done",
                planning_readiness="locked",
            )
            self.schools.append(school)

            # Give every other school some real progress data so the
            # progress-computation path is actually exercised.
            if i % 2 == 0:
                SsaRecord.objects.create(
                    school=school,
                    date_of_ssa=timezone.now(),
                    fy="2026",
                    quarter="Q1",
                    verification_status="confirmed",
                    uploaded_by="tester",
                )
                Activity.objects.create(
                    fy="2026",
                    quarter="Q1",
                    activity_type="school_visit",
                    school=school,
                    status="completed",
                )
                Activity.objects.create(
                    fy="2026",
                    quarter="Q1",
                    activity_type="training",
                    school=school,
                    status="completed",
                )

    def test_school_directory_query_count_is_bounded_not_linear_in_school_count(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        self.client.force_login(self.admin_user)

        with CaptureQueriesContext(connection) as small:
            response = self.client.get("/schools", {"page": 1})
        self.assertEqual(response.status_code, 200)
        small_count = len(small.captured_queries)

        # Add more schools with the same progress-data shape and confirm the
        # query count for rendering a page does NOT grow with total schools
        # in the system (pagination is fixed at 15/page) — this is the
        # signature of a fixed N+1 rather than a real per-page cost.
        from apps.activities.models import Activity
        from apps.ssa.models import SsaRecord
        from django.utils import timezone

        for i in range(12, 40):
            school = School.objects.create(
                school_id=f"PERF-{i}",
                name=f"Perf School {i}",
                region=self.region,
                district=self.district,
                sub_county=self.sub_county,
                school_type="core" if i % 2 == 0 else "client",
                current_fy_ssa_status="not_done",
                planning_readiness="locked",
            )
            if i % 2 == 0:
                SsaRecord.objects.create(
                    school=school,
                    date_of_ssa=timezone.now(),
                    fy="2026",
                    quarter="Q1",
                    verification_status="confirmed",
                    uploaded_by="tester",
                )
                Activity.objects.create(
                    fy="2026",
                    quarter="Q1",
                    activity_type="school_visit",
                    school=school,
                    status="completed",
                )

        with CaptureQueriesContext(connection) as large:
            response = self.client.get("/schools", {"page": 1})
        self.assertEqual(response.status_code, 200)
        large_count = len(large.captured_queries)

        # Page size is fixed (15) — a flat/bounded query plan must not grow
        # meaningfully once the total school count nearly quadruples (12 -> 40).
        self.assertLessEqual(
            large_count,
            small_count + 5,
            f"Query count grew from {small_count} to {large_count} when total "
            "schools grew from 12 to 40 with a fixed page size — this is the "
            "signature of a per-row N+1 in the school directory.",
        )


class StaffDirectoryQueryCountTest(TestCase):
    """Regression test for the staff directory N+1 + unbounded queryset
    (Phase 3 perf audit). staff_directory_view used to iterate every active
    User with no pagination and run 2 extra queries per row (school_count,
    completed_visits). Both the row count on the page and the query count
    must now be flat regardless of total headcount.
    """

    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create(
            id="admin-staffperf-1",
            email="admin-staffperf@edify.org",
            name="Admin Staff Perf",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
            status="active",
        )
        self.admin_user.set_password("pass123")
        self.admin_user.save()

        from apps.activities.models import Activity
        from apps.schools.models import School
        from apps.geography.models import Region, District, SubCounty

        region = Region.objects.create(name="Staff Perf Region")
        district = District.objects.create(name="Staff Perf District", region=region)
        sub_county = SubCounty.objects.create(
            name="Staff Perf Subcounty", district=district
        )
        self.school = School.objects.create(
            school_id="STAFFPERF-1",
            name="Staff Perf School",
            region=region,
            district=district,
            sub_county=sub_county,
            school_type="client",
        )

        self._make_staff_with_activity(User, Activity, count=12, prefix="sp")

    def _make_staff_with_activity(self, User, Activity, count, prefix):
        for i in range(count):
            u = User.objects.create(
                id=f"{prefix}-user-{i}",
                email=f"{prefix}{i}@edify.org",
                name=f"Staff {prefix.upper()} {i}",
                roles=["CCEO"],
                active_role="CCEO",
                is_active=True,
                status="active",
            )
            u.set_password("pass123")
            u.save()
            StaffProfile.objects.create(id=f"{prefix}-profile-{i}", user=u)
            Activity.objects.create(
                fy="2026",
                quarter="Q1",
                activity_type="school_visit",
                school=self.school,
                status="completed",
                responsible_staff_id=u.id,
            )

    def test_staff_directory_is_paginated(self):
        """The row count on a single page must not scale with total headcount."""
        self.client.force_login(self.admin_user)
        response = self.client.get("/staff", {"page": 1})
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(response.context["staff"]),
            20,
            "staff directory page must be paginated (<=20 rows), not dump every "
            "active user unbounded",
        )

    def test_staff_directory_query_count_is_bounded_not_linear_in_staff_count(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from apps.accounts.models import User as AccountsUser
        from apps.activities.models import Activity

        self.client.force_login(self.admin_user)

        with CaptureQueriesContext(connection) as small:
            response = self.client.get("/staff", {"page": 1})
        self.assertEqual(response.status_code, 200)
        small_count = len(small.captured_queries)

        # Nearly triple total headcount; page size is fixed so the query
        # count for rendering a page should stay flat.
        self._make_staff_with_activity(AccountsUser, Activity, count=28, prefix="sq")

        with CaptureQueriesContext(connection) as large:
            response = self.client.get("/staff", {"page": 1})
        self.assertEqual(response.status_code, 200)
        large_count = len(large.captured_queries)

        self.assertLessEqual(
            large_count,
            small_count + 5,
            f"Query count grew from {small_count} to {large_count} when total "
            "staff grew from 12 to 40 with a fixed page size — this is the "
            "signature of a per-row N+1 in the staff directory.",
        )


class LeaveTrackerQueryCountTest(TestCase):
    """Regression test for the leave tracker N+1 (Phase 3 perf audit).

    leave_tracker_view used to call LeaveBalanceService.initialize_
    balances_for_staff() (up to ~7 queries) plus 4 more per-staff queries
    for balances/leaves inside a Python loop over every staff profile in
    scope — unbounded for HR/CD. The query count must now stay flat as
    headcount grows.
    """

    def setUp(self):
        User = get_user_model()
        self.hr_user = User.objects.create(
            id="hr-perf-1",
            email="hr-perf@edify.org",
            name="HR Perf User",
            roles=["HumanResources"],
            active_role="HumanResources",
            is_active=True,
            status="active",
        )
        self.hr_user.set_password("pass123")
        self.hr_user.save()

        self._make_staff(count=6, prefix="lt")

    def _make_staff(self, count, prefix):
        User = get_user_model()
        from apps.accounts.models import Leave

        for i in range(count):
            u = User.objects.create(
                id=f"{prefix}-user-{i}",
                email=f"{prefix}{i}@edify.org",
                name=f"Leave Staff {prefix.upper()} {i}",
                roles=["CCEO"],
                active_role="CCEO",
                is_active=True,
                status="active",
            )
            u.set_password("pass123")
            u.save()
            sp = StaffProfile.objects.create(id=f"{prefix}-profile-{i}", user=u)
            Leave.objects.create(
                staff=sp,
                type="personal_time_off",
                start_date="2026-08-01",
                end_date="2026-08-05",
                days=5,
                status="approved",
            )

    def test_leave_tracker_renders(self):
        self.client.force_login(self.hr_user)
        response = self.client.get("/leave/tracker")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.context["team"]), 6)

    def test_leave_tracker_query_count_is_bounded_not_linear_in_staff_count(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        self.client.force_login(self.hr_user)

        with CaptureQueriesContext(connection) as small:
            response = self.client.get("/leave/tracker")
        self.assertEqual(response.status_code, 200)
        small_count = len(small.captured_queries)

        # Triple the team size and confirm the query count doesn't scale
        # linearly with staff count.
        self._make_staff(count=12, prefix="lu")

        with CaptureQueriesContext(connection) as large:
            response = self.client.get("/leave/tracker")
        self.assertEqual(response.status_code, 200)
        large_count = len(large.captured_queries)

        self.assertLessEqual(
            large_count,
            small_count + 8,
            f"Query count grew from {small_count} to {large_count} when team "
            "size grew from 6 to 18 — this is the signature of a per-row N+1 "
            "in the leave tracker.",
        )


class ChampionsListQueryCountTest(TestCase):
    """Regression test for the champions list N+1 (Phase 3 perf audit).

    champions_list_view used to run a CoreSchoolProfile query + an SsaRecord
    query per champion school, plus unfetched district/region FKs. Query
    count must now stay flat as the champion count grows.
    """

    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create(
            id="admin-champperf-1",
            email="admin-champperf@edify.org",
            name="Admin Champ Perf",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
            status="active",
        )
        self.admin_user.set_password("pass123")
        self.admin_user.save()

        self.region = Region.objects.create(name="Champ Region")
        self.district = District.objects.create(
            name="Champ District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Champ Subcounty", district=self.district
        )
        self._make_champions(count=3, prefix="ch")

    def _make_champions(self, count, prefix):
        from apps.ssa.models import SsaRecord
        from django.utils import timezone

        for i in range(count):
            school = School.objects.create(
                school_id=f"{prefix.upper()}-{i}",
                name=f"Champion School {prefix}{i}",
                region=self.region,
                district=self.district,
                sub_county=self.sub_county,
                school_type="champion",
            )
            SsaRecord.objects.create(
                school=school,
                date_of_ssa=timezone.now(),
                fy="2026",
                quarter="Q1",
                verification_status="confirmed",
                average_score=85.0,
                uploaded_by="tester",
            )

    def test_champions_list_query_count_is_bounded_not_linear_in_champion_count(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        self.client.force_login(self.admin_user)

        with CaptureQueriesContext(connection) as small:
            response = self.client.get("/core-schools/champions")
        self.assertEqual(response.status_code, 200)
        small_count = len(small.captured_queries)

        self._make_champions(count=9, prefix="cj")

        with CaptureQueriesContext(connection) as large:
            response = self.client.get("/core-schools/champions")
        self.assertEqual(response.status_code, 200)
        large_count = len(large.captured_queries)

        self.assertLessEqual(
            large_count,
            small_count + 3,
            f"Query count grew from {small_count} to {large_count} when "
            "champion count grew from 3 to 12 — this is the signature of a "
            "per-row N+1 in the champions list.",
        )
