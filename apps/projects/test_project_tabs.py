"""Each project in a tab of its own (owner, 2026-10-02).

"the project assigned schools on the project monitoring should be organized
in tabs with each project in its tab. On the project coordinator side, all
projects should be organized in tabs not below each project table. It should
be easy for the users to toggle between tabs."

Project Monitoring and the coordinator's Projects page used to draw one card
per project down the page, and the planning queue a Project drop-down. Each
now has a strip naming every project, and draws the open one.
"""

from __future__ import annotations

from apps.projects.models import Project, ProjectSchoolAssignment
from apps.projects.test_project_monitoring_schools import _Fixture


class _TwoProjects(_Fixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.second = Project.objects.create(
            code="TAB-2",
            name="Second Tab Project",
            category="pilot",
            status="active",
            intervention="leadership",
            manager_staff_id=cls.coord.id,
        )
        ProjectSchoolAssignment.objects.create(
            project=cls.second, school=cls.unplanned.school
        )


class ProjectMonitoringTabsTest(_TwoProjects):
    def _page(self, **query):
        self.client.force_login(self.coord_user)
        response = self.client.get("/projects/monitoring", {"fy": self.fy, **query})
        self.assertEqual(response.status_code, 200)
        return response

    def test_every_project_is_a_tab_and_one_is_open(self):
        response = self._page()
        body = response.content.decode()
        self.assertIn("data-project-tabs", body)
        self.assertNotIn('<select name="project"', body)
        tabs = response.context["project_tabs"]
        self.assertEqual(
            {tab["key"] for tab in tabs}, {self.project.id, self.second.id}
        )
        self.assertEqual(sum(tab["is_active"] for tab in tabs), 1)
        self.assertEqual(body.count("data-project-monitoring="), 1)

    def test_a_tab_opens_its_project(self):
        body = self._page(project=self.second.id).content.decode()
        self.assertIn(f'data-project-monitoring="{self.second.id}"', body)
        self.assertNotIn(f'data-project-monitoring="{self.project.id}"', body)

    def test_an_unknown_project_falls_back_to_the_first(self):
        response = self._page(project="no-such-project")
        self.assertEqual(response.content.decode().count("data-project-monitoring="), 1)

    def test_the_stage_filter_keeps_the_open_tab(self):
        body = self._page(project=self.second.id).content.decode()
        self.assertIn(f'name="project" value="{self.second.id}"', body)

    def test_the_table_names_the_district(self):
        body = self._page(project=self.project.id).content.decode()
        self.assertIn('<th scope="col">District</th>', body)
        self.assertIn('data-label="District"', body)


class CoordinatorProjectsPageTabsTest(_TwoProjects):
    def _page(self, **query):
        self.client.force_login(self.coord_user)
        response = self.client.get("/projects", query)
        self.assertEqual(response.status_code, 200)
        return response

    def test_the_projects_are_tabs_and_the_open_card_is_drawn_open(self):
        response = self._page()
        body = response.content.decode()
        self.assertIn("data-project-tabs", body)
        self.assertEqual(body.count("data-project-card="), 1)
        open_id = response.context["open_project"]
        self.assertIn(f'data-project-card="{open_id}"', body)
        # Open already: it fetches its schools as it loads, with no chevron.
        self.assertIn("cardExpanded: true", body)
        self.assertNotIn("cluster-card__toggle", body)
        for project in (self.project, self.second):
            self.assertIn(f"tab={project.id}", body)

    def test_a_tab_opens_its_project(self):
        body = self._page(tab=self.second.id).content.decode()
        self.assertIn(f'data-project-card="{self.second.id}"', body)
        self.assertNotIn(f'data-project-card="{self.project.id}"', body)

    def test_the_card_roster_has_the_school_id_and_district(self):
        self.client.force_login(self.coord_user)
        response = self.client.get(f"/partials/projects/{self.project.id}/schools")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for heading in ("School ID", "School", "District"):
            self.assertIn(f">{heading}</th>", body)


class PlanningQueueTabsTest(_TwoProjects):
    def test_the_queue_has_a_tab_per_project_and_no_project_drop_down(self):
        self.client.force_login(self.coord_user)
        response = self.client.get("/projects/planning")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("data-project-tabs", body)
        self.assertIn('id="spp-project" type="hidden" name="project"', body)
        self.assertNotIn('<select aria-label="Project" name="project">', body)
        self.assertIn("<span>All projects</span>", body)
        self.assertIn(f"<span>{self.second.name}</span>", body)
        for heading in ("School ID", "District"):
            self.assertIn(f'<th scope="col">{heading}</th>', body)
