"""The shared evidence grade (IA review, 2026-09-13).

One rule for how much a figure can bear, on every IA surface: fewer than
MIN_N measured schools is insufficient; a before-and-after reading is at most
descriptive; only a sound comparison with similar schools is associational;
and nothing is ever graded causal.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.analytics import evidence_strength as es


class EvidenceGradeTests(SimpleTestCase):
    def test_below_the_floor_is_insufficient_whatever_the_design(self):
        for design in (es.PRE_POST, es.STRATIFIED_COMPARISON):
            with self.subTest(design=design):
                result = es.grade(es.MIN_N - 1, n_comparison=50, design=design)
                self.assertEqual(result["grade"], es.INSUFFICIENT)
                self.assertEqual(result["min_n"], es.MIN_N)
        self.assertEqual(es.grade(0)["grade"], es.INSUFFICIENT)
        self.assertEqual(es.grade(None)["grade"], es.INSUFFICIENT)

    def test_before_and_after_is_descriptive_at_best(self):
        result = es.grade(200, confirmed_share=1.0, missing_share=0.0)
        self.assertEqual(result["grade"], es.DESCRIPTIVE)
        self.assertIn("no comparison group", " ".join(result["reasons"]))

    def test_a_sound_comparison_is_associational(self):
        result = es.grade(
            20,
            n_comparison=20,
            confirmed_share=1.0,
            missing_share=0.1,
            design=es.STRATIFIED_COMPARISON,
        )
        self.assertEqual(result["grade"], es.ASSOCIATIONAL)
        self.assertEqual(result["label"], es.LABELS[es.ASSOCIATIONAL])
        self.assertTrue(result["design_label"])

    def test_each_weakness_caps_a_comparison_at_descriptive_and_says_why(self):
        base = dict(n_comparison=20, design=es.STRATIFIED_COMPARISON)
        cases = {
            "thin comparison": dict(base, n_comparison=3),
            "heavy missingness": dict(base, missing_share=0.7),
            "unconfirmed readings": dict(base, confirmed_share=0.5),
            "immature cohort": dict(base, flags=(es.IMMATURE_COHORT,)),
            "proxy measure": dict(base, flags=(es.PROXY_MEASURE,)),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                result = es.grade(20, **kwargs)
                self.assertEqual(result["grade"], es.DESCRIPTIVE)
                self.assertGreaterEqual(len(result["reasons"]), 2)
        flagged = es.grade(20, flags=(es.IMMATURE_COHORT,), **base)
        self.assertIn(es.FLAG_TEXT[es.IMMATURE_COHORT], flagged["reasons"])

    def test_no_input_ever_produces_a_causal_grade(self):
        for n in (0, 8, 1000):
            for design in (es.PRE_POST, es.STRATIFIED_COMPARISON, "randomised"):
                result = es.grade(n, n_comparison=n, confirmed_share=1.0, design=design)
                self.assertIn(result["grade"], es.GRADES)
                self.assertNotIn("causal", result["grade"])
                if result["grade"] != es.INSUFFICIENT:
                    self.assertIn(
                        "Association is not proof", " ".join(result["reasons"])
                    )

    def test_every_grade_has_a_tone(self):
        for value in es.GRADES:
            self.assertIn(es.grade_tone(value), ("neutral", "warning", "info"))
