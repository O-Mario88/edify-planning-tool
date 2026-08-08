"""Contracts for Phase 3 executive, people and project mobile homes."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class PhaseThreeMobileRoleHomeContractTest(SimpleTestCase):
    ROLE_TEMPLATES = (
        "templates/pages/dashboards/main.html",
        "templates/pages/dashboards/cd.html",
        "templates/pages/dashboards/rvp.html",
        "templates/pages/dashboards/hr.html",
        "templates/pages/dashboards/special_projects.html",
    )

    def test_each_phase_three_role_has_a_task_first_mobile_opening(self):
        for path in self.ROLE_TEMPLATES:
            with self.subTest(path=path):
                source = _read(path)
                self.assertIn("components/mobile_role_home.html", source)
                self.assertIn("mobile_primary_action", source)
                self.assertIn("mobile-home-hide", source)

    def test_executive_and_people_metrics_follow_attention(self):
        cd = _read("templates/partials/dashboards/cd/body.html")
        hr = _read("templates/partials/dashboards/hr/body.html")
        rvp = _read("templates/pages/dashboards/rvp.html")

        self.assertLess(cd.index("Leadership Attention"), cd.index("Country pulse"))
        self.assertLess(
            hr.index("Leadership Attention Required"), hr.index("People pulse")
        )
        self.assertLess(rvp.index("Leadership Attention"), rvp.index("Regional pulse"))

    def test_admin_and_project_mobile_queues_precede_metrics(self):
        admin = _read("templates/pages/dashboards/main.html")
        projects = _read("templates/pages/dashboards/special_projects.html")

        self.assertLess(
            admin.index("admin-mobile-critical-title"), admin.index("Platform pulse")
        )
        self.assertLess(
            projects.index("projects-mobile-portfolio-title"),
            projects.index("mobile-home-metrics"),
        )

    def test_role_actions_are_selected_from_scoped_view_data(self):
        dashboard = _read("apps/frontend/views/dashboard_views.py")
        for marker in (
            'data.get("leadership_attention")',
            'data.get("attention")',
            'data.get("reviews_due")',
            'context["mobile_primary_action"]',
            '"url": "/projects"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, dashboard)

    def test_partner_today_branches_admin_and_field_officer_copy(self):
        partner = _read("templates/pages/partner/today.html")
        view = _read("apps/frontend/views/partner_views.py")
        self.assertIn("is_partner_admin", partner)
        self.assertIn("Portfolio day", partner)
        self.assertIn("Your work today", partner)
        self.assertIn("EdifyRole.PARTNER_ADMIN.value", view)
