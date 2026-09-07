"""Creating a record is a button that opens the platform drawer.

The owner asked for two related things on 2026-09-07: editing a cost setting
should be a drawer rather than an inline row, and "every add new… is a button
(New users, new school, new cost, new activity…)".

Both were the same problem in different clothes. A `<summary>` inside a
`<details>` reads as a heading and behaves like a disclosure, and an anchor
painted as a button is a link — neither is the control the reader thinks they
are pressing. And a create form that unfolds inline pushes the list it belongs
to off the screen, which is what made the cost register unusable: one row grew
to five times the height of its neighbours.

This module pins the affordance and the surface for the four the owner named,
and the two page-local duplicates removed on the way.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def _opens_drawer(markup: str, label: str) -> bool:
    """Is `label` on a <button> that targets the drawer container?"""
    for match in re.finditer(r"<button\b[^>]*>(.*?)</button>", markup, re.S):
        if label.lower() in re.sub(r"<[^>]+>", " ", match.group(1)).lower():
            if 'hx-target="#drawer-container"' in match.group(0):
                return True
    return False


class CostSettingEditIsADrawerTest(SimpleTestCase):
    def setUp(self):
        self.row = _read("templates/partials/cost_settings/cost_setting_row.html")
        self.drawer = _read("templates/partials/cost_settings/edit_drawer.html")
        self.view = _read("apps/frontend/views/finance_views.py")

    def test_the_row_stays_a_row(self):
        """It used to unfold a three-field form and the whole change-history
        table into one cell spanning three columns."""
        self.assertNotIn("mode == 'edit'", self.row)
        self.assertNotIn("<form", self.row)

    def test_edit_opens_the_drawer(self):
        self.assertTrue(_opens_drawer(self.row, "Edit"), self.row[:400])

    def test_the_drawer_is_a_drawer(self):
        self.assertIn(
            '{% extends "components/drawers/base_drawer.html" %}', self.drawer
        )
        self.assertIn('class="drawer-footer"', self.drawer)

    def test_the_drawer_asks_for_the_prices_and_the_reason(self):
        for field in ('name="unit_cost"', 'name="approved_minimum"', 'name="reason"'):
            with self.subTest(field=field):
                self.assertIn(field, self.drawer)

    def test_the_reason_is_required(self):
        """A rate feeds every activity budget in the country."""
        after = self.drawer.split('name="reason"', 1)[1][:300]
        self.assertIn("required", after)

    def test_the_change_history_travels_with_the_form(self):
        self.assertIn("Change history", self.drawer)

    def test_the_view_serves_the_drawer_for_an_edit(self):
        self.assertIn(
            'return render(request, "partials/cost_settings/edit_drawer.html", context)',
            self.view,
        )

    def test_saving_closes_the_drawer_and_re_reads_the_page(self):
        """A saved rate publishes a NEW catalogue version, so it is not this
        row alone that changed — every row shows a version."""
        self.assertIn('closing["HX-Trigger"] = "close-drawer"', self.view)


class CreateIsAButtonTest(SimpleTestCase):
    """Every "add new…" the owner named opens the drawer from a real button."""

    CASES = {
        "Add new cost": "templates/pages/cost_settings/index.html",
        "New activity": "templates/pages/settings/activity_catalogue.html",
        "Add School": "templates/pages/schools/index.html",
        "Add Partner": "templates/pages/admin/users.html",
    }

    def test_each_one_is_a_button_that_opens_the_drawer(self):
        for label, path in self.CASES.items():
            with self.subTest(label=label):
                self.assertTrue(
                    _opens_drawer(_read(path), label),
                    f"{label} in {path} is not a button targeting #drawer-container",
                )

    def test_no_create_form_unfolds_inline_any_more(self):
        """The two disclosures these buttons replaced."""
        self.assertNotIn(
            'details id="add-cost"', _read("templates/pages/cost_settings/index.html")
        )
        self.assertNotIn(
            'details id="new-activity"',
            _read("templates/pages/settings/activity_catalogue.html"),
        )

    def test_the_new_drawers_extend_the_platform_drawer(self):
        for path in (
            "templates/partials/cost_settings/add_drawer.html",
            "templates/partials/catalogue/new_activity_drawer.html",
        ):
            with self.subTest(path=path):
                self.assertIn(
                    '{% extends "components/drawers/base_drawer.html" %}', _read(path)
                )


class OnePlaceToCreateEachRecordTest(SimpleTestCase):
    """A page-local copy of a form that already exists as a drawer is a second
    thing to maintain, and only one of the two ever is."""

    def test_the_school_directory_uses_the_platform_onboarding_drawer(self):
        page = _read("templates/pages/schools/index.html")
        self.assertIn('hx-get="/schools/create-drawer"', page)
        self.assertNotIn("addSchoolOpen", page)

    def test_the_user_admin_uses_the_platform_partner_drawer(self):
        page = _read("templates/pages/admin/users.html")
        self.assertIn('hx-get="/partners/create"', page)
        self.assertNotIn("showPartnerModal", page)
