"""One percentage implementation, and the difference between 0 and nothing.

Five modules each defined `_pct`, and four of them returned `0` for an empty
denominator while HR's returned `None`. The HR one is right: "no schools in
scope" is not "0% assessed", and "no targets set" is not "0% achieved".

These tests pin both behaviours and, more importantly, pin that the four call
sites which still show a zero are now doing it through a function that says so
in its name -- so nobody has to read four implementations to find out which
answer they are getting.
"""

from __future__ import annotations

import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.core.metrics import percentage, percentage_or_zero

APPS = Path(settings.BASE_DIR) / "apps"


class PercentageTests(SimpleTestCase):
    def test_a_normal_share_is_a_whole_number(self):
        self.assertEqual(percentage(1, 4), 25)

    def test_it_rounds_rather_than_truncates(self):
        self.assertEqual(percentage(2, 3), 67)

    def test_a_zero_numerator_over_a_real_denominator_is_a_measured_zero(self):
        self.assertEqual(percentage(0, 12), 0)

    def test_an_empty_denominator_is_nothing_not_zero(self):
        self.assertIsNone(percentage(0, 0))

    def test_a_none_denominator_is_also_nothing(self):
        self.assertIsNone(percentage(5, None))

    def test_everything_of_everything_is_one_hundred(self):
        self.assertEqual(percentage(7, 7), 100)


class PercentageOrZeroTests(SimpleTestCase):
    def test_it_agrees_with_percentage_whenever_there_is_a_denominator(self):
        for numerator, denominator in ((1, 4), (2, 3), (0, 12), (7, 7)):
            with self.subTest(f"{numerator}/{denominator}"):
                self.assertEqual(
                    percentage_or_zero(numerator, denominator),
                    percentage(numerator, denominator),
                )

    def test_an_empty_denominator_reads_as_zero(self):
        self.assertEqual(percentage_or_zero(0, 0), 0)

    def test_it_never_returns_none(self):
        self.assertIsNotNone(percentage_or_zero(3, 0))


class NoModuleKeepsItsOwnCopyTests(SimpleTestCase):
    """A metric that means two things needs two names -- not five copies."""

    def test_no_app_module_defines_its_own_pct(self):
        offenders = []
        for path in APPS.rglob("*.py"):
            text = path.as_posix()
            if "__pycache__" in text or "/migrations/" in text:
                continue
            if path.name.startswith("test_") or path.name == "ratio.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name in (
                    "_pct",
                    "_percent",
                ):
                    offenders.append(f"{path.relative_to(APPS)}:{node.lineno}")

        self.assertEqual(
            offenders,
            [],
            "use apps.core.metrics.percentage (or percentage_or_zero, which "
            f"names the compromise) instead of a local copy: {offenders}",
        )
