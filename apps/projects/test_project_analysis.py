"""Project Monitoring's Analysis: each watched project read by the engine.

Owner, 2026-10-18: "make sure the existing analytics are integrated into the
profiles and oversights ... oversights (... project monitoring ...)". A
project's row is its profile's read (`profile_intelligence.project_scope`),
narrowed to the enrolments the reader's Monitoring lens shows: the whole
project for Impact Assessment, the Country Director and the coordinator, and
"only the schools they added" for a CCEO or a Programme Lead (owner,
2026-09-21).
"""

from __future__ import annotations

from apps.analytics import profile_intelligence as engine
from apps.projects import project_analysis as analysis
from apps.projects.test_project_monitoring import _Fixture


class RowsTest(_Fixture):
    def test_the_whole_project_reads_as_its_profile_does(self):
        rows = analysis.project_rows(self.ia_user, fy=str(self.fy))

        self.assertEqual(len(rows), 1)
        row = rows[0]
        profile = engine.build(engine.project_scope(self.project), str(self.fy))
        self.assertEqual(row["schools"], 2)
        self.assertEqual(row["schools"], profile["portfolio"]["schools"])
        self.assertEqual(
            row["trainings"]["planned"],
            profile["execution"]["trainings"]["planned"],
        )
        self.assertEqual(row["href"], f"/projects/{self.project.id}?tab=overview")

    def test_an_officer_reads_only_the_schools_they_added(self):
        mine = analysis.project_rows(self.mine_user, fy=str(self.fy))[0]
        whole = analysis.project_rows(self.ia_user, fy=str(self.fy))[0]

        self.assertEqual(mine["schools"], 1)
        # One of the project's three trainings is at the officer's school.
        self.assertLess(mine["trainings"]["planned"], whole["trainings"]["planned"])

    def test_the_coordinator_reads_the_projects_they_run_whole(self):
        rows = analysis.project_rows(self.coordinator_user, fy=str(self.fy))

        self.assertEqual([r["schools"] for r in rows], [2])

    def test_a_reader_who_added_no_school_has_no_project(self):
        self.assertEqual(analysis.project_rows(self.lead_user, fy=str(self.fy)), [])


class PageTest(_Fixture):
    def test_the_analysis_lists_each_project_with_its_profile_link(self):
        self.client.force_login(self.mine_user)

        response = self.client.get("/projects/monitoring/analysis")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("data-project-analysis", body)
        self.assertIn("PM Literacy Project", body)
        self.assertIn(f"/projects/{self.project.id}?tab=overview", body)

    def test_monitoring_and_analysis_are_one_switch_apart(self):
        self.client.force_login(self.mine_user)

        monitoring = self.client.get("/projects/monitoring").content.decode()
        analysed = self.client.get("/projects/monitoring/analysis").content.decode()

        self.assertIn('href="/projects/monitoring/analysis"', monitoring)
        self.assertIn('href="/projects/monitoring"', analysed)
