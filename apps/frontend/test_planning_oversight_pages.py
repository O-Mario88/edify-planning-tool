"""The oversight pages, exercised through their real routes.

The service tests prove the arithmetic. These prove the things only the page
can be wrong about: who may open it, whose work it shows, and — the rule the
whole design rests on — that supervising somebody's work never comes with the
ability to change it.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from django.test import Client, TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School

PL_URL = "/team-planning-oversight/"
CD_URL = "/country-planning-oversight/"


class OversightPageFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )

        cls.pl_user, cls.pl = cls._staff(
            "pl@t.test", "Team Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.james_user, cls.james = cls._staff("james@t.test", "James", EdifyRole.CCEO)
        cls.rival_pl_user, cls.rival_pl = cls._staff(
            "rival@t.test", "Other Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.rival_user, cls.rival = cls._staff(
            "rc@t.test", "Rival CCEO", EdifyRole.CCEO
        )
        cls.cd_user, cls.cd = cls._staff(
            "cd@t.test", "Director", EdifyRole.COUNTRY_DIRECTOR
        )
        cls.ia_user, cls.ia = cls._staff(
            "ia@t.test", "Impact Analyst", EdifyRole.IMPACT_ASSESSMENT
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.james, supervisor=cls.pl
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.rival, supervisor=cls.rival_pl
        )

        cls.school = cls._school("s1", "Alpha Primary")
        cls.rival_school = cls._school("s2", "Rival Primary")
        StaffSchoolAssignment.objects.create(staff=cls.james, school_id=cls.school.id)
        StaffSchoolAssignment.objects.create(
            staff=cls.rival, school_id=cls.rival_school.id
        )
        cls.partner = Partner.objects.create(name="Partner X", active_status=True)

        cls.james_activity = cls._activity(cls.james, cls.school, cost=75_000)
        cls.rival_activity = cls._activity(cls.rival, cls.rival_school, cost=42_000)

    @classmethod
    def _staff(cls, email, name, role):
        user = User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title=name)

    @classmethod
    def _school(cls, school_id, name):
        return School.objects.create(
            school_id=school_id, name=name, district=cls.district, region=cls.region
        )

    @classmethod
    def _activity(cls, owner, school, cost=0):
        planned = date.today() + timedelta(days=5)
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=school,
            fy=cls.fy,
            quarter="Q1",
            planned_date=planned,
            planned_month=planned.month,
            status="scheduled",
            responsible_staff_id=owner.id,
        )
        if cost:
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                cost_setting_key="transport",
                label="Transport",
                unit_cost=cost,
                quantity=1,
                amount=cost,
            )
        return activity

    def as_user(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client


class RouteAccessTest(OversightPageFixture):
    def test_the_program_lead_page_opens_for_a_program_lead(self):
        response = self.as_user(self.pl_user).get(PL_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Planning Oversight")
        # The lens strip, renamed when Country Planning Oversight started
        # drawing the same one (owner, 2026-09-16): "Planning & Portfolio"
        # became "Team Plan", beside the portfolio lens it used to stand for.
        self.assertContains(response, "Team Plan")
        self.assertContains(response, "Team Portfolio")
        self.assertNotContains(response, "Cluster Performance")
        self.assertContains(response, "Target Performance")

    def test_the_country_page_opens_for_the_country_director(self):
        response = self.as_user(self.cd_user).get(CD_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Country Planning Oversight")

    def test_the_country_page_opens_for_impact_assessment(self):
        response = self.as_user(self.ia_user).get(CD_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Country Planning Oversight")

    def test_a_cceo_cannot_open_either_oversight_page(self):
        client = self.as_user(self.james_user)
        for url in (PL_URL, CD_URL):
            with self.subTest(url=url):
                self.assertNotEqual(client.get(url).status_code, 200)

    def test_a_program_lead_cannot_open_the_country_page(self):
        """Supervising a team is not a country remit."""
        self.assertNotEqual(self.as_user(self.pl_user).get(CD_URL).status_code, 200)

    def test_a_country_director_opens_the_team_page_grouped_by_program_lead(self):
        response = self.as_user(self.cd_user).get(PL_URL)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Programme Lead teams")
        self.assertContains(response, "Team Lead")
        self.assertContains(response, "Other Lead")


class ScopeTest(OversightPageFixture):
    def test_programme_lead_tabs_are_people_not_workflow_statuses(self):
        body = self.as_user(self.pl_user).get(PL_URL).content.decode()

        self.assertIn("My Work", body)
        self.assertIn("James", body)
        for removed in (
            "All Planned Work",
            "Partner Work",
            "Needs Attention",
            ">Completed<",
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, body)

    def test_selecting_a_cceo_opens_staff_and_partner_work_they_manage(self):
        response = self.as_user(self.pl_user).get(PL_URL, {"owner": self.james.id})
        body = response.content.decode()

        # The team tab is the officer choice; the rows are that officer's one
        # panel, with no second officer strip under it (owner, 2026-09-25).
        panels = response.context["panel_groups"]
        self.assertEqual([str(group["id"]) for group in panels], [str(self.james.id)])
        self.assertNotIn("team-officer-tab", body)
        self.assertIn("Alpha Primary", body)
        self.assertNotIn("Rival Primary", body)

    def test_the_whole_team_is_one_panel_and_the_tabs_share_a_row(self):
        response = self.as_user(self.pl_user).get(PL_URL)
        body = response.content.decode()

        self.assertEqual(len(response.context["panel_groups"]), 1)
        self.assertEqual(response.context["panel_groups"][0]["name"], "Whole team")
        self.assertIn("Alpha Primary", body)
        self.assertNotIn("team-officer-tab", body)
        self.assertIn('class="oversight-tab-row"', body)
        # No Filters disclosure; one Export menu, in the page header.
        self.assertNotIn("oversight-filters", body)
        self.assertEqual(body.count("data-oversight-export"), 1)

    def test_period_control_offers_week_month_quarter_and_fy(self):
        body = self.as_user(self.pl_user).get(PL_URL).content.decode()

        self.assertIn('name="period"', body)
        self.assertIn('type="week"', body)
        for value in ("week", "month", "quarter", "fy"):
            with self.subTest(value=value):
                self.assertIn(f'<option value="{value}"', body)

    def test_week_period_reaches_the_selected_cceo_rows(self):
        week = self.james_activity.planned_date.strftime("%G-W%V")
        response = self.as_user(self.pl_user).get(
            PL_URL,
            {"owner": self.james.id, "period": "week", "week": week},
        )

        self.assertEqual(response.context["period"], "week")
        self.assertContains(response, "Alpha Primary")

    def test_the_page_shows_supervised_work_and_not_another_team(self):
        body = (
            self.as_user(self.pl_user)
            .get(PL_URL, {"owner": self.james.id})
            .content.decode()
        )

        self.assertIn("Alpha Primary", body)
        self.assertNotIn("Rival Primary", body)

    def test_the_country_page_shows_every_team(self):
        body = self.as_user(self.cd_user).get(CD_URL).content.decode()

        self.assertIn("Team Lead", body)
        self.assertIn("Other Lead", body)

    def test_the_country_page_renders_lead_rows_and_team_expansion_for_ia(self):
        """IA monitors the activity of Program Leads and CCEOs across the country plan."""
        # IA accesses the country planning oversight page's Country Plan lens
        # — the activity plan the page opened on until the planning-coverage
        # dashboard became its first lens (owner, 2026-09-28).
        response = self.as_user(self.ia_user).get(CD_URL, {"view": "plan"})
        self.assertEqual(response.status_code, 200)
        # Each Program Lead is a tab (2026-09-19 redesign); opening it loads
        # the team's detail from its own route.
        self.assertContains(response, 'role="tab"')
        self.assertContains(response, f"/country-planning-oversight/team/{self.pl.id}")
        self.assertContains(response, "Team Lead")
        self.assertContains(response, "Other Lead")

        # IA opens Team Lead's tab: officers are tabs of their own, each
        # holding the officer's work.
        team_resp = self.as_user(self.ia_user).get(
            f"/country-planning-oversight/team/{self.pl.id}"
        )
        self.assertEqual(team_resp.status_code, 200)
        self.assertContains(team_resp, "cd-team-detail-wrapper")
        self.assertContains(team_resp, "team-officer-tab")
        self.assertContains(team_resp, "James")
        self.assertContains(team_resp, "Alpha Primary")

    def test_the_team_expansion_cannot_be_pointed_at_another_team(self):
        """The id in the URL is not trusted; the rows are rebuilt for the caller.

        A Program Lead cannot reach the expansion at all, so the check that
        matters is that the route is gated rather than merely unlinked.
        """
        response = self.as_user(self.pl_user).get(
            f"/country-planning-oversight/team/{self.rival_pl.id}"
        )
        self.assertNotEqual(response.status_code, 200)


class ReadOnlyTest(OversightPageFixture):
    """A Program Lead may supervise a CCEO's activity but never change it."""

    MUTATION_MARKERS = (
        "/activities/{id}/reschedule",
        "/activities/{id}/cancel",
        "/activities/{id}/start",
        "/activities/{id}/complete",
        "/planning/schedule-action",
        "/planning/assign-partner-action",
    )

    def test_the_page_offers_no_control_that_changes_supervised_work(self):
        body = (
            self.as_user(self.pl_user)
            .get(PL_URL, {"owner": self.james.id})
            .content.decode()
        )

        for marker in self.MUTATION_MARKERS:
            route = marker.format(id=self.james_activity.id)
            with self.subTest(route=route):
                self.assertNotIn(route, body)

    def test_the_page_posts_nothing(self):
        """No form the page itself renders submits anything.

        Asked for as an HTMX fragment so the assertion covers the page's own
        markup rather than the shell's chrome — the sign-out form lives in the
        layout and belongs to every page.
        """
        body = (
            self.as_user(self.pl_user)
            .get(PL_URL, headers={"HX-Request": "true"})
            .content.decode()
        )

        posts = re.findall(r'<form[^>]*method=["\']post["\']', body, re.I)
        self.assertEqual(posts, [], "the oversight page must not submit anything")

    def test_the_country_page_posts_nothing(self):
        body = (
            self.as_user(self.cd_user)
            .get(CD_URL, headers={"HX-Request": "true"})
            .content.decode()
        )

        posts = re.findall(r'<form[^>]*method=["\']post["\']', body, re.I)
        self.assertEqual(posts, [])


class MoneyOnThePageTest(OversightPageFixture):
    def test_an_unscheduled_partner_assignment_stays_on_partner_monitoring(self):
        # Partner work stays on Partner Monitoring (owner, 2026-09-26: "partner
        # visits should remain on the partner oversight"); Team Oversight's
        # tables are the team's own work.
        PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.james.id,
            monitoring_staff_id=self.james.id,
            expected_activity_type="school_visit",
            status="assigned",
        )
        client = self.as_user(self.pl_user)

        team = client.get(PL_URL, {"owner": self.james.id}).content.decode()
        partner = client.get("/partner-oversight/").content.decode()

        self.assertNotIn("Partner yet to schedule", team)
        self.assertIn("Awaiting Schedule", partner)

    def test_the_headline_budget_equals_the_cost_lines_in_scope(self):
        body = (
            self.as_user(self.pl_user)
            .get(PL_URL, {"owner": self.james.id})
            .content.decode()
        )

        # James's activity is the only costed work in this PL's scope.
        self.assertIn("UGX 75,000", body)
        self.assertNotIn("42,000", body)


class RosterOpensOnWorkTest(OversightPageFixture):
    """A roster lists the Programme Lead first whether or not they hold work
    (2026-09-23). The officer strip keeps that order but opens on the first
    person with work, so the page never lands on an empty panel — the table
    under the tabs is what e2e/calm-workspace.spec.js reads above the fold."""

    def test_the_team_page_opens_on_the_first_member_holding_work(self):
        response = self.as_user(self.ia_user).get(PL_URL, {"program_lead": self.pl.id})

        self.assertEqual(response.status_code, 200)
        groups = response.context["groups"]
        self.assertEqual(groups[0]["id"], self.pl.id)
        self.assertEqual(groups[0]["items"], [])
        self.assertEqual(response.context["default_officer"], self.james.id)
        self.assertRegex(
            response.content.decode(),
            rf"tabState\('activeOfficer', 'officer', \[[^\]]*\], '{self.james.id}'\)",
        )

    def test_the_country_team_expansion_opens_on_the_same_member(self):
        response = self.as_user(self.ia_user).get(
            f"/country-planning-oversight/team/{self.pl.id}"
        )

        self.assertEqual(response.context["default_officer"], self.james.id)


class SpecialProjectsOversightTest(OversightPageFixture):
    def test_ia_can_view_special_projects_tab_on_planning_oversight(self):
        client = self.as_user(self.ia_user)
        response = client.get(PL_URL, {"view": "projects"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Special Projects")
        self.assertContains(response, "Fiscal year")
        self.assertContains(response, "Planning stage")
        self.assertContains(response, "Project status")
        self.assertContains(response, "All schools")
        self.assertContains(response, "Project schools")
        self.assertContains(response, "Assigned to partner")
        self.assertContains(response, "Activity scheduled")
        self.assertContains(response, "data-project-status-filter")

        # Lens tabs ordering: Planning Monitor -> Special Projects -> Execution & Completion
        lens_tabs = response.context["lens_tabs"]
        keys = [tab["key"] for tab in lens_tabs]
        self.assertIn("projects", keys)
        self.assertIn("monitor", keys)
        self.assertIn("execution", keys)
        self.assertEqual(keys.index("projects"), keys.index("monitor") + 1)
        self.assertEqual(keys.index("execution"), keys.index("projects") + 1)

    def test_country_oversight_workspace_no_longer_has_cpo_notice(self):
        client = self.as_user(self.cd_user)
        response = client.get(CD_URL)
        self.assertEqual(response.status_code, 200)
        # cpo-notice was moved from Country Planning Oversight to Planning Oversight Special Projects tab
        self.assertNotContains(response, "data-cpo-project-tables")

    def test_ia_sees_export_button_on_project_and_can_export(self):
        from apps.projects.models import Project, ProjectSchoolAssignment

        project = Project.objects.create(
            name="Test Special Project",
            code="SP-TEST",
            category="pilot",
            status="active",
        )
        ProjectSchoolAssignment.objects.create(
            project=project,
            school=self.school,
            assigned_by=self.james.id,
        )
        client = self.as_user(self.ia_user)
        # Two exports in the page's heading (owner, 2026-10-05): every
        # project in one file, and the project whose tab is open.
        response = client.get(PL_URL, {"view": "projects"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-project-export-all")
        response = client.get(PL_URL, {"view": "projects", "project": project.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-project-export-all")
        self.assertContains(response, f'data-project-export="{project.id}"')

        # Export single project
        export_url = f"/team-planning-oversight/projects/{project.id}/export"
        export_resp = client.get(export_url)
        self.assertEqual(export_resp.status_code, 200)
        self.assertEqual(
            export_resp["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("SP-TEST", export_resp["Content-Disposition"].upper())

        # Export single project as CSV
        csv_resp = client.get(f"{export_url}?format=csv")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("text/csv", csv_resp["Content-Type"])
        self.assertContains(csv_resp, self.school.name)

        # Export all projects
        all_export_url = "/team-planning-oversight/projects/export"
        all_resp = client.get(all_export_url)
        self.assertEqual(all_resp.status_code, 200)
        self.assertIn("special-projects-schools", all_resp["Content-Disposition"])

    def test_role_without_export_permission_cannot_export_projects(self):
        from apps.projects.models import Project

        project = Project.objects.create(
            name="Restricted Project",
            code="SP-RESTRICTED",
            category="pilot",
            status="active",
        )
        # James is CCEO - does not hold Permission.EXPORT
        client = self.as_user(self.james_user)
        export_url = f"/team-planning-oversight/projects/{project.id}/export"
        response = client.get(export_url)
        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(response.status_code, 302)

        # HTMX request gets 403
        htmx_resp = client.get(export_url, HTTP_HX_REQUEST="true")
        self.assertEqual(htmx_resp.status_code, 403)

    def test_project_coordinator_sees_export_buttons_and_can_export(self):
        from apps.accounts.models import StaffProfile, User
        from apps.core.rbac import EdifyRole
        from apps.projects.models import Project, ProjectSchoolAssignment

        pc_user = User.objects.create_user(
            email="pc_export_test@test.com",
            name="Project Coordinator Export",
            roles=[EdifyRole.PROJECT_COORDINATOR.value],
            active_role=EdifyRole.PROJECT_COORDINATOR.value,
        )
        pc_staff = StaffProfile.objects.create(
            user=pc_user, title="Project Coordinator"
        )
        project = Project.objects.create(
            name="PC Managed Special Project",
            code="SP-PC-TEST",
            category="pilot",
            status="active",
            manager_staff_id=pc_staff.id,
        )
        ProjectSchoolAssignment.objects.create(
            project=project,
            school=self.school,
            assigned_by=pc_staff.id,
        )

        client = self.as_user(pc_user)

        # 1. Project Monitoring page has export buttons for coordinator
        monitoring_resp = client.get("/projects/monitoring")
        self.assertEqual(monitoring_resp.status_code, 200)
        self.assertContains(monitoring_resp, f'data-project-export="{project.id}"')
        self.assertContains(monitoring_resp, "data-project-export-all")

        # 2. Projects list page has export button
        projects_resp = client.get("/projects")
        self.assertEqual(projects_resp.status_code, 200)
        self.assertContains(projects_resp, f'data-project-export="{project.id}"')
        self.assertContains(projects_resp, "data-project-export-all")

        # 3. Project detail page has export button
        detail_resp = client.get(f"/projects/{project.id}")
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, f'data-project-export="{project.id}"')

        # 4. Coordinator can export single project (Excel)
        single_export = client.get(f"/projects/{project.id}/export")
        self.assertEqual(single_export.status_code, 200)
        self.assertEqual(
            single_export["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("SP-PC-TEST", single_export["Content-Disposition"].upper())

        # 5. Coordinator can export single project as CSV
        csv_resp = client.get(f"/projects/{project.id}/export?format=csv")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("text/csv", csv_resp["Content-Type"])
        self.assertContains(csv_resp, self.school.name)

        # 6. Coordinator can export all their scoped projects
        all_export = client.get("/projects/export")
        self.assertEqual(all_export.status_code, 200)
        self.assertIn("special-projects-schools", all_export["Content-Disposition"])

        # 7. Coordinator cannot export projects outside their scope (e.g. unmanaged project)
        other_project = Project.objects.create(
            name="Other Coordinator Project",
            code="SP-OTHER",
            category="pilot",
            status="active",
        )
        forbidden_resp = client.get(f"/projects/{other_project.id}/export")
        self.assertEqual(forbidden_resp.status_code, 404)


class ProjectCoordinatorSidebarTest(TestCase):
    def test_project_capacity_menu_restored_in_sidebar(self):
        from apps.accounts.models import StaffProfile, User
        from apps.core.navigation import build_sidebar_for_user
        from apps.core.rbac import EdifyRole

        user = User.objects.create_user(
            email="pc@test.com",
            name="Project Coordinator",
            roles=[EdifyRole.PROJECT_COORDINATOR.value],
            active_role=EdifyRole.PROJECT_COORDINATOR.value,
        )
        StaffProfile.objects.create(user=user, title="Project Coordinator")

        sidebar = build_sidebar_for_user(user, "/projects")
        daily_group = next((g for g in sidebar if g["label"] == "DAILY"), None)
        self.assertIsNotNone(
            daily_group, "DAILY group should exist for Project Coordinator"
        )
        item_keys = [item["page_key"] for item in daily_group["items"]]
        self.assertIn("project_capacity", item_keys)
        capacity_item = next(
            item
            for item in daily_group["items"]
            if item["page_key"] == "project_capacity"
        )
        self.assertEqual(capacity_item["url"], "/projects/capacity")
        self.assertEqual(capacity_item["label"], "Project Capacity")
