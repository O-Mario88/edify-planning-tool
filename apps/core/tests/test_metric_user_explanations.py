"""A tile's explanation is written for staff, not for maintainers (controls
audit F-05, 2026-09-14): no module paths, display expressions or query
provenance reach a tooltip or accessible description."""

from __future__ import annotations

import re

from django.test import SimpleTestCase

from apps.core import metrics
from apps.core.metrics.spec import user_explanation

_CODE = re.compile(
    r"apps\.[a-z_]|`|\.py\b|objects\.|filter\(|provenance|display expression|"
    r"\b[a-z]+__[a-z_]+\b|:="
)


class MetricUserExplanationTest(SimpleTestCase):
    def test_no_registered_metric_explains_itself_in_code(self):
        registry = getattr(metrics, "METRIC_REGISTRY", None) or metrics.REGISTRY
        offenders = [
            spec.key for spec in registry if _CODE.search(user_explanation(spec))
        ]
        self.assertEqual(offenders, [])
        self.assertTrue(all(user_explanation(spec) for spec in registry))

    def test_provenance_is_removed_and_the_business_meaning_kept(self):
        class Spec:
            definition = (
                "Share of paired schools whose mean SSA score improved "
                "(apps.ssa.change_rules: the published rule). Uses "
                "apps.core.activity_types.COMPLETED_WORK_STATUSES."
            )
            question = "How widespread is improvement?"
            label = "Schools improved"

        self.assertEqual(
            user_explanation(Spec),
            "Share of paired schools whose mean SSA score improved.",
        )

        class CodeOnly(Spec):
            definition = "The value produced by apps.x.y; query provenance: a := b"

        self.assertEqual(user_explanation(CodeOnly), "How widespread is improvement?")

    def test_the_rendered_tile_carries_the_reader_explanation(self):
        from apps.core.metrics import MetricValue, render_metric

        item = render_metric("country_teachers_trained_count", MetricValue.measured(12))
        definition = item.as_dict()["definition"]
        self.assertNotRegex(definition, _CODE)
        self.assertIn("teachers", definition.lower())
