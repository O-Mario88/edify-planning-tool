"""The Regional Programme Lead (owner, 2026-09-12).

"Create a role for Regional program lead who oversee all the program leads in
the region. He can see all the activities of the CCEOs grouped by program
leads, follow up with the program leads. He should NOT approve funds, plan
school activities, non school activities etc. he has regional oversight but on
only CCEOs and PLs activities and he can follow up on the priorities of the
PLs, etc"

Two halves, and the second is the point of the role: what it reads, and what
it is refused.

Then the role description (owner, same day): the Regional Lead for
Christ-Centered Education directs and coaches the country programme teams of
their region "across multiple operational countries". So the reach is whole
countries, and the home is a dashboard built for coaching and reporting.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffGeographyAssignment,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


def _person(uid, email, name, role, country="Uganda"):
    user = User.objects.create(
        id=uid, email=email, name=name, roles=[role], active_role=role, is_active=True
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=uid.upper(), country=country, title=role
    )
    return user, profile


class RegionalProgramLeadTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Two countries, so "regional" has to mean something: the lead is
        # assigned one Ugandan region, reads all of Uganda (the sibling
        # region), and nothing of Kenya.
        cls.region = Region.objects.create(name="RPL Region", country="Uganda")
        cls.sibling_region = Region.objects.create(
            name="Sibling Region", country="Uganda"
        )
        cls.other_region = Region.objects.create(name="Other Region", country="Kenya")
        cls.sibling_district = District.objects.create(
            name="Sibling District", region=cls.sibling_region, district_type="primary"
        )
        cls.district = District.objects.create(
            name="RPL District", region=cls.region, district_type="primary"
        )
        cls.other_district = District.objects.create(
            name="Other District", region=cls.other_region, district_type="primary"
        )
        SubCounty.objects.create(name="RPL Sub", district=cls.district)
        cls.school = School.objects.create(
            school_id="RPL-SCH",
            name="RPL School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.other_school = School.objects.create(
            school_id="RPL-OTHER",
            name="Other Region School",
            region=cls.other_region,
            district=cls.other_district,
            school_type="client",
        )
        cls.sibling_school = School.objects.create(
            school_id="RPL-SIBLING",
            name="Sibling Region School",
            region=cls.sibling_region,
            district=cls.sibling_district,
            school_type="client",
        )

        cls.rpl, cls.rpl_sp = _person(
            "rpl-lead", "rpl@edify.org", "Regional Lead", "RegionalProgramLead"
        )
        StaffGeographyAssignment.objects.create(
            staff=cls.rpl_sp, region_id=cls.region.id
        )
        cls.pl, cls.pl_sp = _person(
            "rpl-pl", "rpl-pl@edify.org", "Lead In Region", "Program Lead"
        )
        cls.cceo, cls.cceo_sp = _person(
            "rpl-cceo", "rpl-cceo@edify.org", "Officer In Region", "CCEO"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo_sp
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)
        cls.school.account_owner_id = cls.cceo_sp.id
        cls.school.save(update_fields=["account_owner_id"])

        cls.other_cceo, cls.other_cceo_sp = _person(
            "rpl-other-cceo",
            "rpl-other@edify.org",
            "Officer Elsewhere",
            "CCEO",
            country="Kenya",
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.other_cceo_sp, school_id=cls.other_school.id
        )

        day = timezone.now() + datetime.timedelta(days=3)
        cls.in_region = Activity.objects.create(
            activity_type="school_visit",
            school=cls.school,
            fy="2026",
            quarter="Q1",
            delivery_type="staff",
            responsible_staff_id=cls.cceo_sp.id,
            status="scheduled",
            scheduled_date=day,
            planned_date=day.date(),
        )
        cls.in_sibling_region = Activity.objects.create(
            activity_type="follow_up_visit",
            school=cls.sibling_school,
            fy="2026",
            quarter="Q1",
            delivery_type="staff",
            responsible_staff_id=cls.cceo_sp.id,
            status="scheduled",
            scheduled_date=day,
            planned_date=day.date(),
        )
        cls.out_of_region = Activity.objects.create(
            activity_type="school_visit",
            school=cls.other_school,
            fy="2026",
            quarter="Q1",
            delivery_type="staff",
            responsible_staff_id=cls.other_cceo_sp.id,
            status="scheduled",
            scheduled_date=day,
            planned_date=day.date(),
        )

    # ── What the role reads ──────────────────────────────────────────────
    def test_the_oversight_scope_is_the_assigned_region_s_country(self):
        from apps.core.scoping import resolve_user_scope
        from apps.planning.oversight_service import resolve_oversight_scope

        scope = resolve_oversight_scope(self.rpl)
        self.assertEqual(scope.kind, "region")
        self.assertTrue(scope.is_region)
        self.assertTrue(scope.groups_by_lead, "the region lens reads many Leads")
        self.assertEqual(
            set(scope.region_ids),
            {self.region.id, self.sibling_region.id},
            "an assigned region stands for its whole country",
        )
        user_scope = resolve_user_scope(self.rpl)
        self.assertEqual(user_scope.region_countries, ["Uganda"])
        self.assertTrue(user_scope.region_assigned)

    def test_it_sees_its_countries_activities_and_not_another_country_s(self):
        from apps.planning.oversight_service import build_items

        ids = {item.activity_id for item in build_items(self.rpl, fy="2026")}
        self.assertIn(self.in_region.id, ids)
        self.assertIn(self.in_sibling_region.id, ids, "the same country's region")
        self.assertNotIn(self.out_of_region.id, ids, "another country")

    def test_the_oversight_page_groups_the_region_by_program_lead(self):
        self.client.force_login(self.rpl)
        page = self.client.get("/team-planning-oversight/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Lead In Region")
        self.assertContains(page, "program_lead=")
        self.assertNotContains(page, "Officer Elsewhere")
        self.assertContains(page, "Regional overview")

    def test_with_no_countries_assigned_it_reads_every_country_and_says_so(self):
        from apps.planning.oversight_service import build_items

        StaffGeographyAssignment.objects.filter(staff=self.rpl_sp).delete()
        ids = {item.activity_id for item in build_items(self.rpl, fy="2026")}
        self.assertIn(self.out_of_region.id, ids, "the RVP's rule for the same gap")
        self.client.force_login(self.rpl)
        page = self.client.get("/team-planning-oversight/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "No countries are assigned to your account yet")

    def test_it_may_follow_up_with_the_program_leads(self):
        from apps.frontend.views.oversight_views import may_delegate

        self.assertTrue(may_delegate(self.rpl, country=False, region=True))
        # …and holds no authority on the country or a single team's lens.
        self.assertFalse(may_delegate(self.rpl, country=True))
        self.assertFalse(may_delegate(self.rpl, country=False))

    def test_the_schools_directory_reads_the_countries_grouped_by_lead(self):
        self.client.force_login(self.rpl)
        page = self.client.get("/schools")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "RPL School")
        self.assertContains(page, "Sibling Region School")
        self.assertNotContains(page, "Other Region School")
        self.assertContains(page, "planning-owner-group")

    def test_the_schools_directory_draws_no_controls_it_cannot_use(self):
        self.client.force_login(self.rpl)
        page = self.client.get("/schools")
        self.assertTrue(page.context["directory_read_only"])
        self.assertNotContains(page, 'id="select-all-schools"')
        self.assertNotContains(page, "school-record-action")
        self.assertContains(page, "Read-only.")

    def test_it_reads_the_priority_register_and_the_leads_targets(self):
        """Follow-up, not authorship: the canonical register and each Lead's
        progress, with none of the controls that set them."""
        self.client.force_login(self.rpl)
        self.assertEqual(self.client.get("/priorities/master").status_code, 200)
        self.assertEqual(self.client.get("/team-targets").status_code, 200)

    # ── Performance it reads (owner, 2026-09-12, second message) ─────────
    def test_ssa_performance_reads_the_country_with_the_breakdowns(self):
        """ "SSA performance by staff, district, cluster, partner, country
        overall" — the intelligence surface is country-wide for this role,
        and the page's own filters narrow it."""
        from apps.analytics.ssa_performance_service import build_dashboard

        dashboard = build_dashboard(self.rpl, {"fy": "2026"})
        self.assertEqual(
            dashboard["kpis"]["total_schools"],
            2,
            "country overall: both Ugandan regions count, Kenya does not",
        )
        self.assertEqual(set(dashboard["breakdowns"]), {"staff", "cluster", "partner"})
        self.client.force_login(self.rpl)
        page = self.client.get("/ssa")
        self.assertEqual(page.status_code, 200)
        for tab in ("staff", "cluster", "partner"):
            self.assertContains(page, f'data-breakdown-tab="{tab}"')

    def test_team_performance_lists_the_region_s_officers_under_their_lead(self):
        from apps.targets.team_targets import supervised_users

        officers = {user.id for user in supervised_users(self.rpl)}
        self.assertIn(self.cceo.id, officers)
        self.assertNotIn(self.other_cceo.id, officers, "another country's officer")
        self.client.force_login(self.rpl)
        page = self.client.get("/team-targets", HTTP_HX_REQUEST="true")
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context["group_by_lead"])
        self.assertEqual(
            [(m["name"], m["lead_name"]) for m in page.context["members"]],
            [("Officer In Region", "Lead In Region")],
        )
        # The progress table itself draws only once officers have agreed
        # targets; when it does, a header row names each Lead.
        from pathlib import Path

        body = Path("templates/partials/targets/team/body.html").read_text()
        self.assertIn("{% ifchanged member.lead_name %}", body)
        self.assertIn('data-lead-group="{{ member.lead_name }}"', body)

    def test_country_priority_progress_reads_the_country_figure(self):
        """The register scopes the target column to the viewer's own
        allocation only for Programme Leads, CCEOs and Project Coordinators;
        everyone else, this role included, reads the country figure."""
        self.client.force_login(self.rpl)
        page = self.client.get("/priorities/master")
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context["is_scoped_viewer"])

    # ── The dashboard (owner, 2026-09-12: "make it enterprise grade") ────
    def test_the_dashboard_is_the_regional_lead_s_own_home(self):
        self.client.force_login(self.rpl)
        page = self.client.get("/dashboard?fy=2026")
        self.assertEqual(page.status_code, 200, "no longer a redirect")
        self.assertTemplateUsed(page, "pages/dashboards/rpl.html")
        self.assertContains(page, "Regional Programme Lead Dashboard")
        self.assertContains(page, "Programme Lead coaching")
        self.assertEqual(page.context["reach"]["countries"], ["Uganda"])
        self.assertEqual(page.context["reach_label"], "Uganda")
        rows = {row["name"]: row for row in page.context["roster"]["rows"]}
        self.assertEqual(rows["Lead In Region"]["planned"], 2)
        self.assertEqual(rows["Lead In Region"]["team_size"], 1)
        self.assertIn(
            "program_lead=" + self.pl_sp.id, rows["Lead In Region"]["oversight_url"]
        )
        self.assertNotContains(page, "Officer Elsewhere")
        families = {row["key"]: row for row in page.context["delivery_mix"]}
        self.assertEqual(families["visits"]["planned"], 1)
        self.assertEqual(families["coaching"]["planned"], 1)
        countries = {row["name"]: row for row in page.context["countries"]}
        self.assertEqual(countries["Uganda"]["planned"], 2)
        self.assertNotIn("Kenya", countries)

    def test_the_dashboard_counts_the_follow_ups_it_sent(self):
        from apps.planning.action_models import TeamAction

        TeamAction.objects.create(
            condition_key="rpl-test:team",
            issue_type="team_backlog",
            school_id=self.school.id,
            fy="2026",
            sender_id=self.rpl.id,
            sender_role="RegionalProgramLead",
            recipient_id=self.pl.id,
            recipient_role="Program Lead",
            requested_action="Clear the team's scheduling backlog",
            workflow_route="/team-planning-oversight/",
            due_date=timezone.localdate() - datetime.timedelta(days=1),
            detected_at=timezone.now(),
        )
        self.client.force_login(self.rpl)
        page = self.client.get("/dashboard?fy=2026")
        follow_ups = page.context["follow_ups"]
        self.assertEqual((follow_ups["active"], follow_ups["overdue"]), (1, 1))
        rows = {row["name"]: row for row in page.context["roster"]["rows"]}
        self.assertEqual(rows["Lead In Region"]["open_follow_ups"], 1)
        self.assertContains(page, "Clear the team&#x27;s scheduling backlog")
        self.assertIn(
            "1 follow-up past due",
            [card["title"] for card in page.context["attention"]],
        )

    def test_the_delivery_families_classify_every_type_once(self):
        from apps.analytics.rpl_dashboard_service import DELIVERY_FAMILIES, _family_of

        seen: dict[str, str] = {}
        for key, _label, _hint, members in DELIVERY_FAMILIES:
            for member in members:
                self.assertNotIn(
                    member, seen, f"{member} in {seen.get(member)} and {key}"
                )
                seen[member] = key
        self.assertEqual(_family_of("training"), "training")
        self.assertEqual(_family_of("follow_up_visit"), "coaching")
        self.assertEqual(_family_of("school_visit"), "visits")
        self.assertEqual(_family_of("cluster_meeting"), "cluster")
        self.assertEqual(_family_of("partner_activity"), "other")

    def test_actions_sent_and_the_schools_directory_are_in_its_sidebar(self):
        from apps.core.navigation import build_sidebar_for_user

        urls = {
            item["url"]
            for section in build_sidebar_for_user(self.rpl, "/dashboard")
            for item in section["items"]
        }
        self.assertIn("/actions/sent", urls, "follow-ups are tracked there")
        self.assertIn("/schools", urls)
        self.assertNotIn("/planning", urls)
        self.client.force_login(self.rpl)
        self.assertEqual(self.client.get("/actions/sent").status_code, 200)

    def test_analytics_aggregates_read_its_countries(self):
        """Every aggregate on /analytics read zero for this role: the shared
        aggregate filter had no branch for it."""
        from apps.core.scoping import aggregate_school_filter, resolve_user_scope

        schools = set(
            School.objects.filter(
                aggregate_school_filter(resolve_user_scope(self.rpl))
            ).values_list("id", flat=True)
        )
        self.assertEqual(schools, {self.school.id, self.sibling_school.id})

    def test_the_analytics_overview_reads_its_countries(self):
        """The overview has its own role branches and had none for this role,
        so it fell to the field path and every figure read zero."""
        from apps.analytics.analytics_dashboard_service import (
            AnalyticsDashboardService,
        )

        School.objects.filter(id=self.school.id).update(enrollment=100)
        School.objects.filter(id=self.sibling_school.id).update(enrollment=50)
        School.objects.filter(id=self.other_school.id).update(enrollment=1000)
        data = AnalyticsDashboardService.get_analytics_data(self.rpl, {"fy": "2026"})
        values = {item["label"]: item["value"] for item in data["kpi_strip_items"]}
        self.assertEqual(
            values["Students Impacted"], "150", "Uganda's two, not Kenya's"
        )

    def test_the_ssa_scope_note_names_the_role_in_words(self):
        from apps.analytics.ssa_performance_service import build_dashboard

        note = build_dashboard(self.rpl, {"fy": "2026"})["scope"]["note"]
        self.assertIn("Regional Program Lead", note)
        self.assertNotIn("RegionalProgramLead", note)

    # ── What the role is refused ─────────────────────────────────────────
    def test_it_holds_no_planning_funding_or_verification_authority(self):
        from apps.core.rbac import Permission
        from apps.core.permissions import has_permission

        for permission in (
            Permission.PLANNING_CREATE,
            Permission.MANUAL_ACTIVITY_CREATE,
            Permission.ACTIVITY_ASSIGN,
            Permission.ACTIVITY_COMPLETE,
            Permission.BUDGET_APPROVE,
            Permission.COUNTRY_BUDGET_APPROVE,
            Permission.IA_VERIFY,
            Permission.STRATEGIC_PRIORITIES_APPROVE,
            Permission.STRATEGIC_PRIORITIES_ALLOCATE,
            Permission.SCHOOL_EDIT,
        ):
            with self.subTest(permission=permission.value):
                self.assertFalse(has_permission(self.rpl, permission.value))

    def test_the_planning_page_and_its_schedule_door_refuse_it(self):
        self.client.force_login(self.rpl)
        # A page this role does not hold redirects to their own home rather
        # than rendering — the platform's refusal for a missing page
        # permission.
        self.assertEqual(self.client.get("/planning")["Location"], "/dashboard")
        refused = self.client.post(
            "/planning/schedule-action",
            {
                "school_id": self.school.id,
                "activity_type": "school_visit",
                "scheduled_date": (timezone.now() + datetime.timedelta(days=5))
                .date()
                .isoformat(),
            },
        )
        self.assertIn(refused.status_code, (403, 405))
        self.assertEqual(
            Activity.objects.filter(school=self.school).count(),
            1,
            "a regional lead must not be able to plan school work",
        )

    def test_the_fund_approval_doors_refuse_it(self):
        self.client.force_login(self.rpl)
        for path in ("/fund-requests/weekly", "/accounts", "/country-budget"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path)["Location"], "/dashboard")

    def test_the_non_school_work_plan_door_refuses_it(self):
        self.client.force_login(self.rpl)
        self.assertEqual(self.client.get("/work-plan/add").status_code, 403)

    def test_it_cannot_reach_the_country_lens(self):
        self.client.force_login(self.rpl)
        self.assertEqual(
            self.client.get("/country-planning-oversight/")["Location"], "/dashboard"
        )


class SsaPerformanceByPartnerTest(TestCase):
    """The partner table counts exactly the work partners collected."""

    def test_the_breakdowns_group_confirmed_results_by_partner_cluster_and_staff(self):
        from apps.analytics.ssa_performance_service import _breakdowns

        schools = [
            {"id": "s1", "account_owner_id": "", "cluster_id": "c1"},
            {"id": "s2", "account_owner_id": "", "cluster_id": "c1"},
            {"id": "s3", "account_owner_id": "", "cluster_id": None},
        ]
        scores = {"leadership": 4.0, "enrolment": 6.0}
        assessed = [
            {
                **schools[0],
                "average": 5.0,
                "scores": scores,
                "is_high_risk": False,
                "partner_id": "p1",
            },
            {
                **schools[1],
                "average": 3.0,
                "scores": {"leadership": 2.0},
                "is_high_risk": True,
                "partner_id": None,
            },
        ]
        result = _breakdowns(assessed, schools)
        cluster = {row["id"]: row for row in result["cluster"]}
        self.assertEqual(cluster["c1"]["schools_assessed"], 2)
        self.assertEqual(cluster["c1"]["total_schools"], 2)
        self.assertEqual(cluster["c1"]["average"], 4.0)
        self.assertEqual(cluster["c1"]["high_risk"], 1)
        partner = {row["id"]: row for row in result["partner"]}
        self.assertEqual(list(partner), ["p1"], "only partner-collected results")
        self.assertEqual(
            partner["p1"]["total_schools"], 1, "a partner has no portfolio denominator"
        )
        self.assertEqual(result["staff"], [], "no owner, no staff row")
