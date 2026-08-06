"""One compact-UGX formatter, so the same amount reads the same on every page.

Twelve private copies existed. The three that were compared directly disagreed:
UGX 1,234,567 rendered as "UGX 1.2M" on the finance and PL approval pages and
"UGX 1.23M" on the budget page, and UGX 2,500 as "UGX 2K" against "UGX 2.50K".
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.core.metrics import format_ugx_compact


class CompactUgxTests(SimpleTestCase):
    def test_the_amount_that_used_to_differ_between_pages(self):
        self.assertEqual(format_ugx_compact(1_234_567), "UGX 1.2M")

    def test_thousands_do_not_carry_false_precision(self):
        # "UGX 2K", not "UGX 2.50K" as the budget page used to render it.
        # The digit is 2 rather than 3 because Python's `:.0f` rounds half to
        # even; every previous copy behaved the same way, so this preserves
        # what the pages already showed.
        self.assertEqual(format_ugx_compact(2_500), "UGX 2K")
        self.assertEqual(format_ugx_compact(3_500), "UGX 4K")

    def test_millions(self):
        self.assertEqual(format_ugx_compact(1_500_000), "UGX 1.5M")

    def test_billions(self):
        self.assertEqual(format_ugx_compact(2_500_000_000), "UGX 2.5B")

    def test_small_amounts_are_exact_and_separated(self):
        self.assertEqual(format_ugx_compact(640), "UGX 640")

    def test_zero(self):
        self.assertEqual(format_ugx_compact(0), "UGX 0")

    def test_none_is_zero_not_a_crash(self):
        self.assertEqual(format_ugx_compact(None), "UGX 0")

    def test_negatives_keep_their_sign_and_still_compact(self):
        """Every previous copy compared `val >= 1_000_000` against a negative,
        which is False, so -1,500,000 fell through to the uncompacted branch
        and rendered as "UGX -1500000" beside compacted positives."""
        self.assertEqual(format_ugx_compact(-1_500_000), "-UGX 1.5M")

    def test_scale_boundaries(self):
        self.assertEqual(format_ugx_compact(999), "UGX 999")
        self.assertEqual(format_ugx_compact(1_000), "UGX 1K")
        self.assertEqual(format_ugx_compact(999_999), "UGX 1000K")
        self.assertEqual(format_ugx_compact(1_000_000), "UGX 1.0M")
        self.assertEqual(format_ugx_compact(1_000_000_000), "UGX 1.0B")


class SingleDefinitionTests(SimpleTestCase):
    def test_the_migrated_modules_share_one_implementation(self):
        from apps.frontend.views import budget_views, finance_operating_views
        from apps.fund_requests import pl_approval_service

        self.assertIs(budget_views.format_ugx_compact, format_ugx_compact)
        self.assertIs(finance_operating_views.format_ugx_compact, format_ugx_compact)
        self.assertIs(pl_approval_service._ugx, format_ugx_compact)
