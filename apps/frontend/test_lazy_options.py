"""Long option lists arrive inert and keep what the select shows and sends.

A select with thousands of options (every sub-county, cluster or loan in
scope) now carries them in `<template data-lazy-options>` and micro-ux.js makes
them options when the select is reached (P-5, owner-approved 2026-09-25). Until
then it must hold its first option and the chosen one, so the closed select
reads, and the form submits, exactly as before; the template must hold the
whole list in the server's order.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


class LazyOptionsTest(SimpleTestCase):
    def _render(self, selected):
        sub_counties = [
            SimpleNamespace(id=n, name=f"Sub-county {n}") for n in (3, 1, 2)
        ]
        return render_to_string(
            "partials/schools/directory_sub_county_filter.html",
            {
                "sub_counties": sub_counties,
                "selected_district": "d1",
                "selected_sub_county": selected,
            },
        )

    def _parts(self, html):
        select = html[html.index("<select") : html.index("</select>")]
        head, template = select.split("<template data-lazy-options>")
        values = lambda text: re.findall(r'<option value="([^"]*)"', text)  # noqa: E731
        return values(head), values(template), select

    def test_the_closed_select_holds_the_first_and_chosen_options(self):
        head, full, select = self._parts(self._render("1"))
        self.assertEqual(head, ["", "1"])
        self.assertIn('<option value="1" selected>', select)
        self.assertEqual(full, ["3", "1", "2"])

    def test_nothing_chosen_leaves_only_the_first_option(self):
        head, full, _select = self._parts(self._render(""))
        self.assertEqual(head, [""])
        self.assertEqual(full, ["3", "1", "2"])

    def test_the_script_counts_and_expands_the_template(self):
        script = (ROOT / "static/js/micro-ux.js").read_text()
        self.assertIn("function expandLazyOptions(select)", script)
        self.assertIn("select.replaceChildren(first, lazy.content)", script)
        # A select whose list is still inert is not an empty filter.
        self.assertIn("!(lazy && lazy.content.childElementCount)", script)
