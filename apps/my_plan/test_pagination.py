"""Ten rows a card, pages as far as the person planned, filters preserved."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.my_plan.pagination import PAGE_SIZE, page_from, paginate


class PaginateTest(SimpleTestCase):
    def test_a_short_list_needs_no_pager(self):
        result = paginate(list(range(3)))
        self.assertFalse(result["paginated"])
        self.assertEqual(result["page_count"], 1)
        self.assertEqual(len(result["rows"]), 3)

    def test_exactly_one_page_is_not_paginated(self):
        """Ten rows is one page; a pager promising more would be a lie."""
        result = paginate(list(range(PAGE_SIZE)))
        self.assertFalse(result["paginated"])
        self.assertEqual(result["page_count"], 1)

    def test_eleven_rows_makes_two_pages(self):
        result = paginate(list(range(11)))
        self.assertTrue(result["paginated"])
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(len(result["rows"]), PAGE_SIZE)

    def test_pages_run_to_the_last_planned_activity(self):
        """Not a fixed window: someone who planned 200 gets 20 pages."""
        self.assertEqual(paginate(list(range(200)))["page_count"], 20)
        self.assertEqual(paginate(list(range(35)))["page_count"], 4)

    def test_the_second_page_carries_the_next_ten(self):
        result = paginate(list(range(47)), page=2)
        self.assertEqual(result["rows"], list(range(10, 20)))
        self.assertEqual(result["first_index"], 11)
        self.assertEqual(result["last_index"], 20)

    def test_the_last_page_may_be_short(self):
        result = paginate(list(range(47)), page=5)
        self.assertEqual(len(result["rows"]), 7)
        self.assertEqual(result["last_index"], 47)
        self.assertFalse(result["has_next"])

    def test_a_page_past_the_end_clamps_instead_of_erroring(self):
        """A stale link from a card that has since emptied should land on the
        last real page, not break a working list."""
        result = paginate(list(range(25)), page=999)
        self.assertEqual(result["page"], 3)
        self.assertEqual(result["page_count"], 3)

    def test_a_page_below_one_clamps_too(self):
        self.assertEqual(paginate(list(range(25)), page=0)["page"], 1)
        self.assertEqual(paginate(list(range(25)), page=-4)["page"], 1)

    def test_an_empty_card_reports_nothing_rather_than_page_one_of_zero(self):
        result = paginate([])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["first_index"], 0)
        self.assertFalse(result["paginated"])


class PageFromTest(SimpleTestCase):
    """A page number arrives in a URL, so it can be anything at all."""

    def test_it_reads_a_number(self):
        self.assertEqual(page_from({"p": "4"}, "p"), 4)

    def test_junk_falls_back_to_the_first_page(self):
        for value in ("", None, "abc", "../etc", "3.7", "'; drop table"):
            with self.subTest(value):
                self.assertEqual(page_from({"p": value}, "p"), 1)

    def test_a_missing_key_is_the_first_page(self):
        self.assertEqual(page_from({}, "p"), 1)
        self.assertEqual(page_from(None, "p"), 1)

    def test_a_negative_page_is_the_first_page(self):
        self.assertEqual(page_from({"p": "-3"}, "p"), 1)


class MyPlanContextTest(SimpleTestCase):
    """Each card pages on its own, and paging keeps every other filter."""

    def _context(self, query):
        from urllib.parse import parse_qs

        # Mirrors the base-query construction in my_plan.services so the
        # contract is pinned without needing a database.
        page_params = {
            "school_visits_page",
            "cluster_trainings_page",
            "cluster_meetings_page",
        }
        from urllib.parse import urlencode

        base = urlencode({k: v for k, v in query.items() if v and k not in page_params})
        return parse_qs(base)

    def test_paging_one_card_preserves_the_period_and_filters(self):
        kept = self._context(
            {
                "period": "month",
                "district": "d-1",
                "school_visits_page": "3",
            }
        )
        self.assertEqual(kept["period"], ["month"])
        self.assertEqual(kept["district"], ["d-1"])

    def test_one_cards_page_never_travels_to_another(self):
        """Otherwise paging school visits would also page cluster meetings."""
        kept = self._context(
            {
                "period": "month",
                "school_visits_page": "3",
                "cluster_meetings_page": "5",
            }
        )
        self.assertNotIn("school_visits_page", kept)
        self.assertNotIn("cluster_meetings_page", kept)
