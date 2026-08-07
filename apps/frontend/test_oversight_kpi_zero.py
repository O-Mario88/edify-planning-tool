"""A measured zero must be legible as a zero.

The KPI strip renders `{% firstof item.display_value item.value %}`, and
`firstof` treats 0 as falsy — so a tile whose value is genuinely zero rendered
as an empty box. On a supervision page that is the worst possible failure mode:
"no partner handovers are stuck" and "nobody has checked" look identical.
"""

from __future__ import annotations

from apps.frontend.views.oversight_views import _kpi_items

from django.test import SimpleTestCase

EMPTY_SUMMARY = {
    "total_planned": 0,
    "staff_scheduled": 0,
    "partner_awaiting_schedule": 0,
    "partner_scheduled": 0,
    "scheduled_total": 0,
    "at_risk": 0,
    "needs_attention": 0,
    "planned_budget": 0,
    "completed": 0,
    "due_count": 0,
    "execution_progress": None,
    "cost_missing": 0,
    "awaiting_verification": 0,
    "awaiting_payment": 0,
}


class ZeroRendersTest(SimpleTestCase):
    def test_every_tile_carries_a_printable_value_when_everything_is_zero(self):
        for tile in _kpi_items(EMPTY_SUMMARY, country=False):
            with self.subTest(tile=tile["label"]):
                self.assertTrue(
                    str(tile.get("display_value", "")),
                    "a zero tile must still print something",
                )

    def test_a_zero_is_shown_as_zero_not_as_blank(self):
        tiles = {t["label"]: t for t in _kpi_items(EMPTY_SUMMARY, country=True)}

        self.assertEqual(tiles["Partner Awaiting Schedule"]["display_value"], "0")
        self.assertEqual(tiles["Country Activities At Risk"]["display_value"], "0")
        self.assertEqual(tiles["Country Planned Activities"]["display_value"], "0")

    def test_a_measured_zero_says_it_was_measured(self):
        """The distinction the tile has to carry, now in the payload itself.

        Since these are built through the metric registry the state travels
        with the number, so "we looked and found none" is a fact about the
        tile rather than an inference from how it happens to render.
        """
        for tile in _kpi_items(EMPTY_SUMMARY, country=True):
            if tile["label"] == "Plan Execution Progress":
                continue  # genuinely unmeasurable here; asserted below
            with self.subTest(tile=tile["label"]):
                self.assertEqual(tile["data_state"], "measured")
                self.assertEqual(tile["value"], 0)

    def test_an_unmeasurable_progress_never_reads_as_zero(self):
        """Nothing due yet is not 0% executed — they mean different things.

        The registry states the reason rather than a bare dash: a dash says
        "no number", the note says why there is no number, and the reader is
        the one who has to tell those apart.
        """
        tiles = {t["label"]: t for t in _kpi_items(EMPTY_SUMMARY, country=False)}
        progress = tiles["Plan Execution Progress"]

        self.assertEqual(progress["data_state"], "not_yet_measurable")
        self.assertIsNone(progress["value"])
        self.assertNotIn("0", progress["display_value"])
        self.assertEqual(progress["display_value"], "Nothing due yet")

    def test_large_numbers_are_grouped_for_reading(self):
        summary = {**EMPTY_SUMMARY, "total_planned": 12345, "planned_budget": 33856000}
        tiles = {t["label"]: t for t in _kpi_items(summary, country=True)}

        self.assertEqual(tiles["Country Planned Activities"]["display_value"], "12,345")
        self.assertEqual(
            tiles["Planned Country Budget"]["display_value"], "UGX 33,856,000"
        )

    def test_the_partner_strip_prints_its_zeros_too(self):
        """The same failure mode, on the page where zero is the common case."""
        from apps.frontend.views.oversight_views import _partner_kpis

        empty = {
            "active_partners": 0,
            "schools_assigned": 0,
            "awaiting_schedule": 0,
            "scheduled": 0,
            "in_progress": 0,
            "returned": 0,
            "at_risk": 0,
            "scheduled_budget": 0,
            "payment_pending": 0,
        }

        for tile in _partner_kpis(empty):
            with self.subTest(tile=tile["label"]):
                self.assertEqual(tile["data_state"], "measured")
                self.assertIn("0", tile["display_value"])
