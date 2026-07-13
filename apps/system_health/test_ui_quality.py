"""Gold Standard UI lints — enforced in CI so regressions can't land.

If any of these fail, someone reintroduced a banned pattern (emoji instead of
an SVG icon, a mock-data marker, a dead link/HX target, a hardcoded chart
series, an uncompiled responsive variant, or a light-only chart grid)."""

from __future__ import annotations

from django.test import TestCase

from apps.system_health.ui_quality import ui_quality_checks


class UIQualityLintTest(TestCase):
    def test_gold_standard_lints_are_clean(self):
        checks = {c["key"]: c for c in ui_quality_checks()["checks"]}
        expected = (
            "mock_smells", "emojis", "dead_links",
            "static_chart_series", "uncompiled_variants", "light_only_grids",
        )
        for key in expected:
            self.assertIn(key, checks)
            self.assertEqual(
                checks[key]["count"], 0,
                f"{key} regressed: {checks[key]['items']}",
            )

    def test_lints_render_on_system_health_report(self):
        from apps.system_health.services import report

        data = report()
        self.assertIn("uiQuality", data)
        self.assertEqual(len(data["uiQuality"]["checks"]), 6)
