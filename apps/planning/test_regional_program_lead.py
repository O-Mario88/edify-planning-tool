"""The Regional Programme Lead (owner, 2026-09-12).

"Create a role for Regional program lead who oversee all the program leads in
the region. He can see all the activities of the CCEOs grouped by program
leads, follow up with the program leads. He should NOT approve funds, plan
school activities, non school activities etc. he has regional oversight but on
only CCEOs and PLs activities and he can follow up on the priorities of the
PLs, etc"

Two halves, and the second is the point of the role: what it reads, and what
it is refused.
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


def _person(uid, email, name, role):
    user = User.objects.create(
        id=uid, email=email, name=name, roles=[role], active_role=role, is_active=True
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=uid.upper(), country="Uganda", title=role
    )
    return user, profile


class RegionalProgramLeadTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Two regions, so "regional" has to mean something.
        cls.region = Region.objects.create(name="RPL Region")
        cls.other_region = Region.objects.create(name="Other Region")
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
            "rpl-other-cceo", "rpl-other@edify.org", "Officer Elsewhere", "CCEO"
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
    def test_the_oversight_scope_is_the_assigned_region(self):
        from apps.planning.oversight_service import resolve_oversight_scope

        scope = resolve_oversight_scope(self.rpl)
        self.assertEqual(scope.kind, "region")
        self.assertTrue(scope.is_region)
        self.assertTrue(scope.groups_by_lead, "the region lens reads many Leads")
        self.assertEqual(scope.region_ids, (self.region.id,))

    def test_it_sees_its_region_s_activities_and_not_another_region_s(self):
        from apps.planning.oversight_service import build_items

        ids = {item.activity_id for item in build_items(self.rpl, fy="2026")}
        self.assertIn(self.in_region.id, ids)
        self.assertNotIn(self.out_of_region.id, ids, "a region is not the country")

    def test_the_oversight_page_groups_the_region_by_program_lead(self):
        self.client.force_login(self.rpl)
        page = self.client.get("/team-planning-oversight/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Lead In Region")
        self.assertContains(page, "program_lead=")
        self.assertNotContains(page, "Officer Elsewhere")
        self.assertContains(page, "Region overview")

    def test_with_no_region_assigned_it_reads_nothing_and_says_why(self):
        StaffGeographyAssignment.objects.filter(staff=self.rpl_sp).delete()
        self.client.force_login(self.rpl)
        page = self.client.get("/team-planning-oversight/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "No region is assigned to your account yet")

    def test_it_may_follow_up_with_the_program_leads(self):
        from apps.frontend.views.oversight_views import may_delegate

        self.assertTrue(may_delegate(self.rpl, country=False, region=True))
        # …and holds no authority on the country or a single team's lens.
        self.assertFalse(may_delegate(self.rpl, country=True))
        self.assertFalse(may_delegate(self.rpl, country=False))

    def test_the_schools_directory_reads_the_region_grouped_by_lead(self):
        self.client.force_login(self.rpl)
        page = self.client.get("/schools")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "RPL School")
        self.assertNotContains(page, "Other Region School")
        self.assertContains(page, "planning-owner-group")

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
            "country overall: both regions' schools count toward the headline",
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
        self.assertNotIn(self.other_cceo.id, officers, "another region's officer")
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
