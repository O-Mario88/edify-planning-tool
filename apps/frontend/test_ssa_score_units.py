import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class SsaScorePresentationContractTest(SimpleTestCase):
    """Keep SSA scores on their canonical 0-10 scale in every UI."""

    def _template(self, relative_path):
        from apps.frontend.template_families import read_template

        return read_template(Path(settings.BASE_DIR), f"templates/{relative_path}")

    def test_score_templates_do_not_render_ssa_values_as_percentages(self):
        templates = Path(settings.BASE_DIR) / "templates"
        forbidden = (
            re.compile(r"\{\{[^}]*\bavg_ssa\b[^}]*\}\}\s*%"),
            re.compile(r"\{\{[^}]*\bssa_avg\b[^}]*\}\}\s*%"),
            re.compile(r"\{\{[^}]*\bssa_improve\b[^}]*\}\}\s*pp\b"),
            re.compile(r"\{\{[^}]*\bweakest_pct\b[^}]*\}\}\s*%"),
        )
        violations = []

        for path in templates.rglob("*.html"):
            source = path.read_text()
            for pattern in forbidden:
                if pattern.search(source):
                    violations.append(
                        f"{path.relative_to(templates)}: {pattern.pattern}"
                    )

        self.assertEqual(
            violations,
            [],
            "SSA scores are native 0-10 values, never percentages:\n"
            + "\n".join(violations),
        )
        assessment = self._template("partials/core_schools/core_assessment_drawer.html")
        self.assertNotIn(
            "{{ score.score }}/10 ({{ score.score_pct }}%)",
            assessment,
            "The score percentage is permitted as an internal bar width only.",
        )

    def test_ssa_heatmaps_use_score_fields_and_percentage_only_for_bar_widths(self):
        score_templates = (
            "partials/dashboards/cd/body.html",
            "partials/dashboards/pl/ssa_intelligence.html",
            "partials/analytics/cd/district_heatmap.html",
            "partials/analytics/cd/ssa_interventions.html",
            "partials/analytics/pl/ssa_interventions.html",
        )
        for path in score_templates:
            source = self._template(path)
            self.assertNotIn("cell.pct", source, path)
            self.assertNotRegex(source, r"\{\{\s*r\.pct\b", path)

        self.assertIn("cell.score", self._template(score_templates[0]))
        self.assertIn("cell.score", self._template(score_templates[1]))
        self.assertIn("cell.score", self._template(score_templates[2]))
        # The two intervention panels draw last cycle's score inside this
        # cycle's (owner, 2026-10-09): the shared track takes the two scores
        # and works the widths out itself, so no percentage is in the panel.
        for path in score_templates[3:]:
            source = self._template(path)
            self.assertIn("components/ssa_cutout_track.html", source, path)
            self.assertIn("current=r.score previous=r.previous", source, path)
        track = self._template("components/ssa_cutout_track.html")
        self.assertIn("current|multiply:10", track)
        self.assertIn("previous|multiply:10", track)

    def test_cd_heatmap_and_priority_school_table_are_separate_cards(self):
        # The two cards live in the operations view since 2026-09-19, and the
        # heatmap reads as a comparison of clusters by intervention.
        source = self._template("partials/dashboards/cd/operations.html")
        start = source.index("data-cd-school-ssa-cards")
        section = source[start : source.index("Country Field Intelligence", start)]

        self.assertIn("Cluster SSA Comparison", section)
        self.assertIn("Priority Schools Needing Urgent Attention", section)
        self.assertEqual(
            section.count("<section"),
            2,
            "The heatmap and priority-school table must remain independent cards.",
        )
        self.assertIn("data-cd-risk-priority-row", section)
        self.assertIn("data-cd-priority-schools-card", section)

    def test_analytics_service_exposes_native_score_and_private_bar_width(self):
        source = (
            Path(settings.BASE_DIR) / "apps" / "analytics" / "pl_analytics_service.py"
        ).read_text()
        self.assertIn("def _ssa_score(", source)
        self.assertIn("def _ssa_bar_pct(", source)
        self.assertNotIn("def _norm(", source)
