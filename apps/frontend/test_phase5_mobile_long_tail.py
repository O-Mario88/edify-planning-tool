"""Contracts for Phase 5 mobile long-tail page families."""

from pathlib import Path

from django.test import SimpleTestCase
from django.urls import resolve


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class PhaseFiveMobileLongTailContractTest(SimpleTestCase):
    def assert_family(self, family: str, pages: tuple[str, ...]):
        marker = f'data-mobile-family="{family}"'
        for path in pages:
            with self.subTest(family=family, path=path):
                self.assertIn(marker, _read(path))

    def test_analytics_pages_share_compact_filter_and_chart_family(self):
        self.assert_family(
            "analytics",
            (
                "templates/pages/analytics/index.html",
                "templates/pages/analytics/cd_analytics.html",
                "templates/pages/analytics/pl_analytics.html",
                "templates/pages/analytics/impact.html",
                "templates/pages/analytics/declining_schools.html",
                "templates/pages/analytics/visit_effectiveness.html",
            ),
        )
        index = _read("templates/pages/analytics/index.html")
        self.assertIn("Analytics filters", index)
        self.assertIn("mobile-family-filter", index)

    def test_performance_pages_share_touch_safe_record_family(self):
        self.assert_family(
            "performance",
            (
                "templates/pages/hr/performance_console.html",
                "templates/pages/hr/my_performance.html",
                "templates/pages/hr/performance_conversation.html",
                "templates/pages/hr/professional_development_dashboard.html",
                "templates/pages/hr/priority_configuration.html",
                "templates/pages/hr/strategic_priorities.html",
                "templates/pages/hr/module_workspace.html",
            ),
        )
        console = _read("templates/pages/hr/performance_console.html")
        self.assertIn("mobile-performance-readiness", console)
        self.assertIn("edify-record-table", console)

    def test_knowledge_settings_and_upload_surfaces_have_explicit_roots(self):
        self.assertIn(
            'data-mobile-family="knowledge"',
            _read("templates/layouts/help_center.html"),
        )
        self.assert_family(
            "settings",
            (
                "templates/pages/settings/index.html",
                "templates/pages/admin/index.html",
                "templates/pages/admin/users.html",
                "templates/pages/admin/roles_permissions.html",
                "templates/pages/admin/workflow_rules.html",
            ),
        )
        self.assert_family(
            "upload",
            (
                "templates/pages/documents/upload_center.html",
                "templates/pages/schools/upload.html",
                "templates/pages/schools/upload_preview.html",
                "templates/pages/ssa/upload_center.html",
                "templates/pages/ssa/upload_preview.html",
                "templates/pages/ssa/upload_result.html",
            ),
        )

    def test_history_and_closure_tables_use_mobile_record_architecture(self):
        self.assert_family(
            "history",
            (
                "templates/pages/admin/audit_log.html",
                "templates/pages/audit/decision_log.html",
                "templates/pages/accounts/approval_history.html",
                "templates/pages/accounts/audit_log.html",
                "templates/pages/ia/verification_history.html",
            ),
        )
        self.assert_family(
            "closure",
            (
                "templates/pages/closure/readiness_queue.html",
                "templates/pages/closure/blocked_closure.html",
                "templates/pages/closure/activity_closure_detail.html",
                "templates/pages/closure/completed_activities.html",
                "templates/pages/closure/completed_detail.html",
            ),
        )
        self.assertIn(
            "edify-record-table",
            _read("templates/pages/audit/decision_log.html"),
        )

    def test_closure_queue_route_is_not_shadowed_by_activity_detail(self):
        match = resolve("/activities/closure")
        self.assertEqual(match.url_name, "closure_readiness")
        self.assertEqual(match.func.__name__, "closure_readiness_queue_view")

    def test_phase_five_css_enforces_compact_grids_and_touch_targets(self):
        styles = _read("static/css/components/mobile-patterns.css")
        for marker in (
            '[data-mobile-family="analytics"]',
            '[data-mobile-family="performance"]',
            '[data-mobile-family="knowledge"]',
            '[data-mobile-family="settings"]',
            '[data-mobile-family="upload"]',
            '[data-mobile-family="history"]',
            '[data-mobile-family="closure"]',
            ".mobile-performance-readiness",
            "min-block-size: 2.75rem",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, styles)
