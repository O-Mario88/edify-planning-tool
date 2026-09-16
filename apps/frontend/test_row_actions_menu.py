"""The row Actions menu opens as a menu, not as one squashed line.

Every control that sits in a table cell is compacted to the row line: 32px
geometry from platform.css's ROW ACTION CONTROLS, a 24px control height from
consistency.css, and `micro-ux.js` marks the elements those rules match.

The row-actions dropdown lives inside a table cell, so its items were marked
too. They took `display: inline-flex` and the 24px height with them, and with
`white-space: nowrap` inherited from the cell the four items laid themselves
out on ONE 34px line — three of them past the menu's own right edge. Clicking
Actions opened something that showed a single item and read as broken.

The boundary is held twice, and both halves are pinned here: the marker pass
stops at a popup, and the stylesheet restates the menu's own geometry at a
specificity the compaction rules cannot reach.
"""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class RowActionsMenuContractTests(SimpleTestCase):
    def test_marker_pass_stops_at_a_popup(self):
        script = _read("static/js/micro-ux.js")

        self.assertIn("function inPopup(element, table)", script)
        for selector in ('[role="menu"]', ".row-menu__list", "[popover]"):
            self.assertIn(selector, script.split("var popupSelector", 1)[1][:300])

        # The two marker writes that handed the menu its cell geometry.
        self.assertIn(
            "action.classList.toggle('edify-table-action', !inPopup(action, table))",
            script,
        )
        self.assertIn("if (inPopup(control, cell)) return;", script)
        self.assertNotIn("action.classList.add('edify-table-action');", script)

    def test_menu_items_stack(self):
        styles = _read("static/css/pages.css")
        rule = styles.split(".row-menu__list .row-menu__item {", 1)[1].split("}", 1)[0]

        # !important, because the compaction rules it overrides use it too.
        self.assertIn("display: block !important", rule)
        self.assertIn("inline-size: 100% !important", rule)
        self.assertIn("block-size: auto !important", rule)
        self.assertIn("max-block-size: none !important", rule)
        self.assertIn("text-align: start !important", rule)

        # The list itself: a block that lets its items wrap out of the cell's
        # inherited nowrap.
        list_rule = styles.split(".row-menu .row-menu__list {", 1)[1].split("}", 1)[0]
        self.assertIn("display: block", list_rule)
        self.assertIn("white-space: normal", list_rule)

    def test_built_stylesheet_carries_the_rule(self):
        """static/build/css is generated; a source-only fix ships nothing."""
        built = _read("static/build/css/pages.css")

        self.assertIn(".row-menu__list .row-menu__item", built)
        self.assertIn(".row-menu .row-menu__list", built)

    def test_every_menu_shares_one_trigger_and_one_item_class(self):
        """The fix is in the shared classes, so it has to be the shared classes
        every menu is built from — a page with its own markup keeps the bug."""
        for template in (
            "templates/partials/my_plan/activity_row.html",
            "templates/partials/today/queue_row.html",
            "templates/partials/dashboards/cceo/week.html",
        ):
            body = _read(template)
            self.assertIn('x-data="rowMenu"', body, template)
            self.assertIn("row-menu__list", body, template)
            self.assertIn("row-menu__item", body, template)
