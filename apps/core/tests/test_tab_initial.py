"""`tab_initial` names the panel `tabState` opens on, so that panel alone can
render without x-cloak (2026-09-24 A+ audit, P-4). A disagreement would paint
one panel and then swap it for another, so the rule is held here to the
browser's (static/js/alpine-components.js, `tabState` / `syncFromUrl`)."""

from __future__ import annotations

from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase

ROWS = [{"id": "a"}, {"id": 7}, {"id": None}]


def initial(query, fallback, suffix="", param="officer"):
    request = RequestFactory().get("/x", query)
    template = Template(
        "{% load table_pagination %}"
        "{% tab_initial rows param fallback suffix=suffix as chosen %}{{ chosen }}"
    )
    return template.render(
        Context(
            {
                "request": request,
                "rows": ROWS,
                "param": param,
                "fallback": fallback,
                "suffix": suffix,
            }
        )
    )


class TabInitialTest(SimpleTestCase):
    def test_a_requested_tab_the_strip_offers_wins(self):
        self.assertEqual(initial({"officer": "7"}, "a"), "7")
        self.assertEqual(initial({"officer": "None"}, "a"), "None")

    def test_an_unoffered_request_falls_back(self):
        self.assertEqual(initial({"officer": "someone-else"}, "7"), "7")
        self.assertEqual(initial({}, "7"), "7")

    def test_an_unoffered_fallback_opens_the_first_tab(self):
        self.assertEqual(initial({}, "my-clusters"), "a")

    def test_a_suffixed_parameter(self):
        # As cluster oversight writes it: `officer-<lead id>`.
        self.assertEqual(initial({"officer-L1": "7"}, "a", "L1", "officer-"), "7")
        self.assertEqual(initial({"officer": "7"}, "a", "L1", "officer-"), "a")
