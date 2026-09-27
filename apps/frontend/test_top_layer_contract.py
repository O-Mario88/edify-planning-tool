"""Everything that floats opens where it belongs.

Owner, 2026-09-27, on the Core Schools Actions menu: "it is not opening on
the button. it looks like it is fixed in one position and hidden ... NO action
button dropdown drawer opens from a fixed position. they have to open where
the button is", then "this should also apply to all fix positions items", and
"make sure the dropdown is actually dropping down (the drawer is down not up
on top of the action button)".

A `position: fixed` box is placed against the nearest ancestor with a
transform, filter, containment or container type, not against the window, and
the platform's container queries put a container type on main, tables, cards
and every Core School row. static/js/top-layer.js shows whatever floats in the
browser's top layer instead: dropdowns down from their button, overlays over
the window. tests/js/top-layer.test.cjs holds the placement to "down, never
over the button"; this file holds every page to the mechanism.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _templates():
    for path in sorted(TEMPLATES.rglob("*.html")):
        yield path, path.read_text(encoding="utf-8")


OPEN_TAG = re.compile(r"<(div|ul|nav|section|span|form|menu)\b([^>]*)>", re.S)


class TopLayerLoadsFirstTests(SimpleTestCase):
    def test_the_layer_loads_before_the_components_that_use_it(self):
        base = _read("templates/base.html")
        layer = base.index("js/top-layer.js")
        self.assertLess(layer, base.index("js/alpine-components.js"))
        self.assertLess(layer, base.index("js/micro-ux.js"))
        self.assertLess(layer, base.index("js/date-picker.js"))
        # Deferred, so it blocks no first paint; deferred scripts run in
        # document order, so it still runs before Alpine and the enhancers.
        tag = base[base.rindex("<script", 0, layer) : base.index(">", layer)]
        self.assertIn("defer", tag)
        self.assertLess(layer, base.index("js/vendor/alpine-3.14.0.min.js"))


class RowActionsOpenFromTheButtonTests(SimpleTestCase):
    def test_row_menu_opens_through_the_layer_down_from_its_button(self):
        script = _read("static/js/alpine-components.js")
        row_menu = script.split("Alpine.data('rowMenu'", 1)[1].split("}));", 1)[0]

        self.assertIn(
            "window.EdifyLayer.open(this.$refs.list, this.$refs.trigger", row_menu
        )
        self.assertIn("align: 'end'", row_menu)
        self.assertIn("onLost: () => this.close()", row_menu)
        self.assertIn("window.EdifyLayer.close(this.$refs.list)", row_menu)
        # Its own coordinates, and the flip above the button, are gone.
        self.assertNotIn("getBoundingClientRect", row_menu)
        self.assertNotIn("this.y", row_menu)

    def test_no_template_positions_a_row_menu_itself(self):
        offenders = []
        for path, text in _templates():
            if "row-menu" not in text:
                continue
            if re.search(r":style=\"`left:\$\{x\}px", text) or "reposition()" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], "row menus are placed by EdifyLayer")


class EveryDropdownOpensFromItsButtonTests(SimpleTestCase):
    """A shown/hidden panel positioned `absolute` a margin below its button is
    a dropdown placed by the page, which a card's hidden overflow can cut off.
    Say `x-dropdown="$refs.button"` (top-layer.js) instead."""

    def test_no_page_hangs_a_dropdown_off_an_absolute_offset(self):
        offenders = []
        for path, text in _templates():
            for match in OPEN_TAG.finditer(text):
                attributes = match.group(2)
                if "x-show=" not in attributes or "x-dropdown" in attributes:
                    continue
                classes = re.search(r'\bclass="([^"]*)"', attributes)
                names = classes.group(1).split() if classes else []
                offset = any(re.fullmatch(r"(sm:|md:|lg:)?mt-[\d.]+", n) for n in names)
                if "absolute" in names and offset:
                    line = text.count("\n", 0, match.start()) + 1
                    offenders.append(f"{path.relative_to(ROOT)}:{line}")
        self.assertEqual(offenders, [])

    def test_converted_dropdowns_name_their_button(self):
        for template, button in (
            ("templates/layouts/shell.html", "accountButton"),
            ("templates/pages/schools/index.html", "exportButton"),
            ("templates/partials/messages/conversation.html", "menuButton"),
            ("templates/partials/core_schools/filters.html", "moreFiltersButton"),
            (
                "templates/partials/schools/directory_intelligence.html",
                "editTypeButton",
            ),
        ):
            text = _read(template)
            self.assertIn(f'x-ref="{button}"', text, template)
            self.assertRegex(
                text, rf'x-dropdown(\.start)?="\$refs\.{button}"', template
            )

    def test_the_attendance_checklist_drops_down_too(self):
        # A popover of its own in the completion drawer, placed by its own
        # script: it used to open above the button near the drawer's foot.
        drawer = _read("templates/partials/my_plan/complete_drawer.html")
        self.assertIn("top: `${rect.bottom + gap}px`", drawer)
        self.assertNotIn("opensAbove", drawer)
        self.assertIn("this.scrollContainer.scrollTop +=", drawer)


class OverlaysCoverTheWindowTests(SimpleTestCase):
    def test_overlays_are_found_from_the_stylesheets(self):
        script = _read("static/js/top-layer.js")
        # Any rule that makes an element position: fixed makes it a candidate,
        # so a new modal or bar is covered without being listed anywhere.
        self.assertIn('getPropertyValue("position").trim() === "fixed"', script)
        self.assertIn('el.getAttribute("data-edify-layer") === "off"', script)
        self.assertIn('Alpine.directive("dropdown"', script)

    def test_a_lifted_element_keeps_its_own_look(self):
        for stylesheet in (
            "static/css/components/interactions.css",
            "static/build/css/components/interactions.css",
        ):
            styles = _read(stylesheet)
            # The browser's popover defaults centre the box and paint it in
            # system colours; the base layer hands it back to its own rules.
            self.assertRegex(
                styles,
                r"@layer base\s*\{\s*:where\(\[data-edify-lifted\]\)",
                stylesheet,
            )
