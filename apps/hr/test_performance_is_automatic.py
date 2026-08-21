"""Achievement is derived, never typed (§11, §16, §25.7).

The rule these defend: no user — not the employee, not their manager, not HR,
not the CD, IA or Admin — can enter an achieved total, a variance, a
percentage or a classification. If a result is wrong, the underlying record is
wrong, and that is what gets corrected.

These are guard tests. They are not testing today's behaviour so much as
stopping tomorrow's: the cheapest way to lose an automatic performance system
is for one well-meaning "let HR correct this figure" field to appear on one
form, and nothing else in the suite would notice.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]

#: Fields that carry a derived performance figure. A form input bound to any
#: of these would let someone type an answer the platform is supposed to work out.
DERIVED_FIELDS = (
    "actual_value",
    "achievement_percentage",
    "system_score",
    "contribution_points",
)

#: Templates that render a performance or target surface.
SURFACE_GLOBS = (
    "templates/pages/hr/*.html",
    "templates/partials/hr/*.html",
    "templates/pages/targets/*.html",
    "templates/partials/targets/*.html",
    "templates/partials/work_plan/*.html",
)


def _surface_templates():
    for pattern in SURFACE_GLOBS:
        yield from REPO.glob(pattern)


class NoTypedAchievementTests(SimpleTestCase):
    def test_no_form_input_is_bound_to_a_derived_figure(self):
        offenders = []
        pattern = re.compile(
            r"<(?:input|textarea|select)[^>]*\bname=[\"']([\w.-]+)[\"']",
            re.IGNORECASE,
        )
        for template in _surface_templates():
            text = template.read_text(encoding="utf-8", errors="ignore")
            for field in pattern.findall(text):
                if field in DERIVED_FIELDS:
                    offenders.append(f"{template.relative_to(REPO)} → {field}")
        self.assertEqual(
            offenders,
            [],
            "a derived performance figure has an editable input: "
            + "; ".join(offenders),
        )

    def test_the_scoring_service_takes_no_achievement_argument(self):
        """Nothing may pass a score in — it can only be read out of records."""
        import inspect

        from apps.hr import performance_scores

        for name in ("staff_overall", "pl_performance", "country_performance"):
            signature = inspect.signature(getattr(performance_scores, name))
            supplied = {
                p
                for p in signature.parameters
                if p in ("achieved", "pct", "score", "classification", "override")
            }
            self.assertEqual(
                supplied, set(), f"{name} accepts a caller-supplied result"
            )

    def test_the_work_plan_exposes_no_write_path(self):
        from apps.monthly_work_plan import schedule_plan

        writers = [
            name
            for name in dir(schedule_plan)
            if name.startswith(("create", "save", "add", "update", "delete", "set_"))
        ]
        self.assertEqual(writers, [])

    def test_classification_cannot_be_supplied_only_derived(self):
        import inspect

        from apps.hr.target_distribution import classify_achievement

        params = set(inspect.signature(classify_achievement).parameters)
        # It takes a percentage and the rules for reading it — never a label.
        self.assertEqual(params, {"pct", "cap_at_100", "target", "scoreable"})
