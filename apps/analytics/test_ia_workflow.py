from datetime import date, timedelta
from unittest.mock import patch

from django.test import RequestFactory
from django.utils import timezone

from apps.analytics.ia_workflow import evidence_row, outcome_workspace
from apps.core.scoping import UserScope
from apps.frontend.test_dashboard_views_shell import _user
from apps.frontend.views.ia_outcome_views import impact_report_download
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.projects.test_ssa_impact import INTERVENTION, ImpactFixture


class IAWorkflowTests(ImpactFixture):
    def setUp(self):
        super().setUp()
        self.user = _user("ia.workflow@edify.test", "ImpactAssessment")
        self.baseline = self._ssa(self.school, date(2025, 1, 1), 0)
        self.follow_up = self._ssa(self.school, date(2026, 1, 1), 2)
        self.assignment = ProjectSchoolAssignment.objects.create(
            project=self.project,
            school=self.school,
            baseline_ssa=self.baseline,
            baseline_score=0,
            follow_up_ssa=self.follow_up,
            follow_up_score=2,
            impact_classification="improved",
            mapping_version=1,
        )

    def test_zero_baseline_is_valid_and_missing_evidence_is_not_decline(self):
        row = evidence_row(self.assignment, date.today())
        self.assertEqual(row["delta"], 2)
        self.assertTrue(row["measured"])
        self.assignment.baseline_score = None
        row = evidence_row(self.assignment, date.today())
        self.assertEqual(row["state"], "baseline_missing")
        self.assertFalse(row["measured"])

    def test_unconfirmed_deleted_or_wrong_school_followup_is_not_measured(self):
        for field, value in (
            ("verification_status", "pending"),
            ("deleted_at", timezone.now()),
            ("school_id", "another-school"),
        ):
            with self.subTest(field=field):
                original = getattr(self.follow_up, field)
                setattr(self.follow_up, field, value)
                self.assertFalse(
                    evidence_row(self.assignment, date.today())["measured"]
                )
                setattr(self.follow_up, field, original)

    def test_collection_dates_distinguish_due_upcoming_and_overdue(self):
        self.assignment.follow_up_ssa = None
        self.assignment.follow_up_score = None
        today = date.today()
        for days, state in ((-1, "overdue"), (0, "due"), (1, "upcoming")):
            self.assignment.follow_up_due_on = today + timedelta(days=days)
            self.assertEqual(evidence_row(self.assignment, today)["state"], state)
        self.assignment.follow_up_due_on = None
        self.assertEqual(evidence_row(self.assignment, today)["state"], "not_scheduled")

    def test_scope_and_project_filters_apply_before_outcome_counts(self):
        hidden = self._school("Hidden")
        ProjectSchoolAssignment.objects.create(project=self.project, school=hidden)
        scope = UserScope(
            user_id=self.user.id,
            active_role="ImpactAssessment",
            school_ids=[self.school.id],
        )
        with patch("apps.analytics.ia_workflow.resolve_user_scope", return_value=scope):
            result = outcome_workspace(self.user, {})
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["measured"], 1)
            self.assertEqual(result["rows"][0]["school_id"], self.school.id)
            self.assertEqual(
                outcome_workspace(self.user, {"project": "unknown"})["total"], 0
            )
            scope.school_ids = []
            self.assertEqual(outcome_workspace(self.user, {})["total"], 0)
            scope.can_view_summary_only = True
            self.assertEqual(outcome_workspace(self.user, {})["total"], 0)

    def test_report_has_evidence_limitations_narrative_and_formula_protection(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/ia/impact-report/download",
            {"findings": "=HYPERLINK(1)", "recommendations": "IA: revisit in October"},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Draft for review", content)
        self.assertIn("'=HYPERLINK(1)", content)
        self.assertIn(self.baseline.id, content)
        self.assertIn("IA: revisit in October", content)
        self.assertIn("not direct proof", content)

    def test_report_requires_export_permission_and_post(self):
        request = RequestFactory().post("/ia/impact-report/download")
        request.user = self.user
        with patch(
            "apps.frontend.views.ia_outcome_views.RolePermissionService.can_export",
            return_value=False,
        ):
            self.assertEqual(impact_report_download(request).status_code, 403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/ia/impact-report/download").status_code, 405)

    def test_all_workflow_tabs_render_and_htmx_preserves_project(self):
        self.client.force_login(self.user)
        for view in ("outcomes", "collection", "framework", "learning", "reports"):
            response = self.client.get(
                "/ia/dashboard/",
                {"view": view, "project": self.project.id},
                HTTP_HX_TARGET="ia-dashboard-view-shell",
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "data-ia-outcome-workspace")
            self.assertContains(response, f"project={self.project.id}")

    def test_default_is_outcomes_and_collection_excludes_measured_records(self):
        self.client.force_login(self.user)
        response = self.client.get("/ia/dashboard/")
        self.assertEqual(response.context["dashboard_view"], "outcomes")
        response = self.client.get("/ia/dashboard/", {"view": "collection"})
        self.assertEqual(response.context["ia_evidence_page"].paginator.count, 0)

    def test_country_boundary_applies_to_download_as_well_as_screen(self):
        from apps.geography.models import Region

        hidden = self._school("Kenya")
        hidden.region = Region.objects.create(name="Kenya Region", country="Kenya")
        hidden.save(update_fields=["region"])
        ProjectSchoolAssignment.objects.create(project=self.project, school=hidden)
        scope = UserScope(
            user_id=self.user.id,
            active_role="ImpactAssessment",
            country_scope=True,
            country="Uganda",
        )
        self.client.force_login(self.user)
        with patch("apps.analytics.ia_workflow.resolve_user_scope", return_value=scope):
            self.assertEqual(outcome_workspace(self.user, {})["total"], 1)
            response = self.client.post("/ia/impact-report/download")
            self.assertNotIn(hidden.id, response.content.decode())

    def test_non_ia_staff_cannot_open_dashboard_or_download_report(self):
        staff = _user("cceo.ia.workflow@edify.test", "CCEO")
        self.client.force_login(staff)
        response = self.client.get("/ia/dashboard/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard")
        self.assertEqual(
            self.client.post("/ia/impact-report/download").status_code, 403
        )


class IAOutcomeCohortTests(ImpactFixture):
    """Project cohorts on the Outcomes view (IA review, owner, 2026-09-13)."""

    def setUp(self):
        super().setUp()
        self.user = _user("ia.cohorts@edify.test", "ImpactAssessment")

    def _enrol(self, school, classification, before, after):
        return ProjectSchoolAssignment.objects.create(
            project=self.project,
            school=school,
            baseline_ssa=self._ssa(school, date(2025, 1, 1), before),
            baseline_score=before,
            follow_up_ssa=self._ssa(school, date(2026, 1, 1), after),
            follow_up_score=after,
            impact_classification=classification,
        )

    def test_no_change_is_neutral_and_kept_strong_stays_out_of_the_change(self):
        from apps.analytics.ia_workflow import _cohort_domains

        kept = self._enrol(self.school, "maintained_strong", 8, 9)
        row = evidence_row(kept, date.today())
        self.assertEqual(row["tone"], "neutral")
        rows = [row] + [
            {**row, "school_id": f"s{i}", "state": "improved", "delta": 1.0}
            for i in range(8)
        ]
        domain = next(d for d in _cohort_domains(rows) if d["code"] == INTERVENTION)
        self.assertEqual(domain["pairs"], 9)
        self.assertEqual(domain["maintained"], 1)
        # The kept-strong enrolment's +1 is not a movement; eight +1.0s are.
        self.assertEqual(domain["delta"], 1.0)
        self.assertEqual(domain["improved_pct"], 89)

    def test_unique_schools_sit_beside_enrolments_and_tiles_say_not_measured(self):
        second = Project.objects.create(
            name="EdTech", code="EDT", intervention=INTERVENTION
        )
        ProjectSchoolAssignment.objects.create(project=self.project, school=self.school)
        ProjectSchoolAssignment.objects.create(project=second, school=self.school)
        with patch(
            "apps.analytics.ia_workflow.resolve_user_scope",
            return_value=UserScope(
                user_id=self.user.id,
                active_role="ImpactAssessment",
                school_ids=[self.school.id],
            ),
        ):
            workspace = outcome_workspace(self.user, {})
        self.assertEqual(workspace["total"], 2)
        self.assertEqual(workspace["unique_schools"], 1)
        tiles = {t["label"]: t for t in workspace["cohort_tiles"]}
        self.assertEqual(
            tiles["Project Enrolments Improved"]["display_value"], "Not measured"
        )
        self.assertFalse(tiles["Project Enrolments Improved"]["is_measured"])
