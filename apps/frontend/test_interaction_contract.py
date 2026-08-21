"""How every control answers a pointer.

Two behaviours, stated once in static/css/components/interactions.css and
guarded here:

  Hover inverts.  A blue control turns white with blue ink; a white control
                  turns blue with white ink. Before this, "hover" meant a
                  slightly darker blue in some families, a faint blue tint in
                  others, and nothing at all for the many buttons written as
                  raw Tailwind utilities.

  Press pushes.   The control shifts down a pixel and drops its shadow, so a
                  click reads as a press rather than a colour flicker.

Tabs are a segmented rail rather than a row of buttons: one track, hairline
rules between segments, the selected one filled. The corners curve only at the
two extreme ends, to the same radius a button uses — a selected middle segment
is a rectangle.

The tests below read the stylesheet rather than a rendered page because these
are contract statements: a rule that exists for one family and not another is
exactly the drift this file was written to end.
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


ROOT = Path(settings.BASE_DIR)
STYLESHEET = "static/css/components/interactions.css"


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _contrast_ratio(foreground, background):
    def luminance(hex_color):
        values = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in values
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted(
        (luminance(foreground), luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


class InteractionContractIsLoadedTest(SimpleTestCase):
    def test_the_stylesheet_is_linked_after_every_other_stylesheet(self):
        """It decides the response over whatever each component decided about
        its resting look, which only holds if it is the last word."""
        base = _read("templates/base.html")
        self.assertIn("css/components/interactions.css", base)

        links = [
            line
            for line in base.splitlines()
            if 'rel="stylesheet"' in line and "{% static 'css/" in line
        ]
        self.assertTrue(links)
        self.assertIn("interactions.css", links[-1])


class HoverInvertsTest(SimpleTestCase):
    def setUp(self):
        self.css = _read(STYLESHEET)

    def test_a_blue_control_turns_into_a_white_one(self):
        self.assertIn(
            "background-color: var(--edify-invert-surface) !important;", self.css
        )
        self.assertIn("color: var(--edify-invert-surface-ink) !important;", self.css)

    def test_a_white_control_turns_into_a_blue_one(self):
        self.assertIn(
            "background-color: var(--edify-invert-fill) !important;", self.css
        )
        self.assertIn("color: var(--edify-invert-fill-ink) !important;", self.css)

    def test_both_families_are_named_not_just_the_component_api(self):
        """Most buttons on this platform are raw utilities. A contract that
        only covered `.btn-primary` would leave the majority behaving the old
        way, which is worse than not having one."""
        for needle in (
            ".btn-premium-primary",
            ".edify-action-button.primary",
            r".bg-\[var\(--edify-primary\)\]",
            r".bg-\[var\(--edify-accent\)\]",
            ".btn-premium-secondary",
            r":is(button, a):is(.rounded-control):is(.border)",
        ):
            self.assertIn(needle, self.css, f"{needle} is outside the contract")

    def test_nested_labels_and_icons_follow_the_inverted_ink(self):
        """A utility colour on a nested span would otherwise repaint the label
        white on a now-white surface."""
        self.assertIn(":is(span, strong, small, svg, b)", self.css)

    def test_hover_rules_are_guarded_for_touch(self):
        """A tap must not leave a control stuck in its hover state."""
        self.assertIn("@media (hover: hover)", self.css)

    def test_both_inversion_pairs_meet_aa_in_the_light_theme(self):
        tokens = _read("static/css/design-system.css")
        fill = self._token(tokens, "--brand-primary")
        ink_on_fill = self._token(tokens, "--brand-primary-on-solid")
        ink_on_surface = self._token(tokens, "--brand-primary-text")

        self.assertGreaterEqual(_contrast_ratio(ink_on_fill, fill), 4.5)
        self.assertGreaterEqual(_contrast_ratio(ink_on_surface, "#ffffff"), 4.5)

    @staticmethod
    def _token(tokens, name):
        for line in tokens.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{name}:"):
                return stripped.split(":", 1)[1].strip().rstrip(";")
        raise AssertionError(f"{name} is not defined")


class PressPushesTest(SimpleTestCase):
    def setUp(self):
        self.css = _read(STYLESHEET)

    def test_the_control_moves_down_rather_than_only_changing_colour(self):
        self.assertIn("--edify-press-shift: 1px;", self.css)
        self.assertIn(
            "transform: translateY(var(--edify-press-shift)) !important;", self.css
        )

    def test_the_press_is_removed_for_reduced_motion(self):
        """The whole press block sits inside the no-preference query, so a
        person who asked for less movement gets none rather than a shorter
        one."""
        self.assertIn("@media (prefers-reduced-motion: no-preference)", self.css)
        head, _, tail = self.css.partition(
            "@media (prefers-reduced-motion: no-preference)"
        )
        self.assertNotIn("translateY(var(--edify-press-shift))", head)
        self.assertIn("translateY(var(--edify-press-shift))", tail)

    def test_tabs_press_too(self):
        self.assertIn('[role="tab"]', self.css)


class SegmentedTabsTest(SimpleTestCase):
    def setUp(self):
        self.css = _read(STYLESHEET)

    def test_segments_are_square_and_only_the_rail_ends_curve(self):
        self.assertIn("border-radius: 0 !important;", self.css)
        self.assertIn("padding: 0 !important;", self.css)
        self.assertIn("align-self: stretch !important;", self.css)
        self.assertIn("block-size: auto !important;", self.css)
        self.assertIn("height: auto !important;", self.css)
        self.assertIn("min-block-size: 0 !important;", self.css)
        self.assertIn(
            "border-start-start-radius: var(--edify-radius-sm) !important;", self.css
        )
        self.assertIn(
            "border-end-end-radius: var(--edify-radius-sm) !important;", self.css
        )

    def test_the_rail_wraps_its_segments_without_reserved_space_below(self):
        rail_contract = self.css.split(
            "Tabs: a segmented rail, not a row of buttons", 1
        )[1].split('main :is(\n  [role="tab"]', 1)[0]
        self.assertIn("padding: 0 !important;", rail_contract)
        self.assertIn("min-block-size: 0 !important;", rail_contract)
        self.assertIn("block-size: auto !important;", rail_contract)
        self.assertIn("height: auto !important;", rail_contract)

    def test_the_end_radius_is_the_button_radius_not_a_pill(self):
        """A rail and a button should read as the same family of control."""
        self.assertNotIn("var(--edify-radius-pill)", self.css)
        tokens = _read("static/css/design-system.css")
        self.assertIn("--edify-radius-sm: var(--radius-control);", tokens)

    def test_decorative_children_do_not_change_end_segment_geometry(self):
        """Grouped navigation has hidden labels before its first real tab."""
        for selector in (
            ".edify-section-nav__cluster:first-of-type",
            ".edify-section-nav__cluster:last-of-type",
            ".edify-section-nav__link:first-of-type",
            ".edify-section-nav__link:last-of-type",
        ):
            self.assertIn(selector, self.css)

        first_cluster = self.css.split(
            "main .edify-section-nav__clusters > "
            ".edify-section-nav__cluster:first-of-type,",
            1,
        )[1]
        self.assertIn(
            "border-start-start-radius: var(--edify-radius-sm) !important;",
            first_cluster,
        )

        # The first real segment also owns the rail edge without a stray
        # divider, exactly like a simple tablist whose tab is :first-child.
        no_rule_block = self.css.split("No rule before the first segment", 1)[1]
        self.assertIn(".edify-section-nav__cluster:first-of-type", no_rule_block)
        self.assertIn("--edify-segment-rule: transparent;", no_rule_block)

    def test_segments_are_divided_by_a_rule(self):
        self.assertIn("--edify-segment-rule", self.css)
        self.assertIn(")::before {", self.css)

    def test_no_rule_touches_a_filled_segment(self):
        """A hairline running into the blue fill reads as a rendering fault."""
        self.assertIn("--edify-segment-rule: transparent;", self.css)

    def test_the_selected_segment_is_filled_rather_than_raised(self):
        self.assertIn("background: var(--edify-invert-fill) !important;", self.css)
        self.assertIn("color: var(--edify-invert-fill-ink) !important;", self.css)

    def test_hovering_a_tab_does_not_fill_it(self):
        """Inversion is for buttons, where hover means "this is what you are
        about to do". A rail is a set of choices and only one is true; filling
        a segment blue under the pointer says "selected" about every one of
        them in turn, and the rail flashes as the mouse crosses it.

        The only hover rule left for tabs keeps the SELECTED segment from
        losing its fill when the pointer lands on it.
        """
        hover_blocks = [
            block
            for block in self.css.split("@media (hover: hover)")[1:]
            if 'role="tab"' in block
        ]
        self.assertTrue(hover_blocks, "no tab hover rule at all")
        for block in hover_blocks:
            body = block[: block.find("\n}\n\n/*")] if "\n}\n\n/*" in block else block
            for selector_group in body.split("}"):
                if ":hover" not in selector_group:
                    continue
                if '[role="tab"]:hover' in selector_group.replace(" ", ""):
                    self.fail("an unselected tab still inverts on hover")

    def test_a_selected_tab_keeps_its_fill_under_the_pointer(self):
        selected_hover = self.css.split("@media (hover: hover)")[-1]
        self.assertIn('[role="tab"][aria-selected="true"]', selected_hover)
        self.assertIn(
            "background: var(--edify-invert-fill) !important;", selected_hover
        )

    def test_the_tab_ink_outranks_a_page_level_utility(self):
        """The bug this catches shipped for a moment: with :where() the rail's
        fill won but its ink lost to a Tailwind text colour on the active tab,
        leaving dark blue on blue at about 1.5:1."""
        self.assertNotIn("main :where(", self.css)
        self.assertIn("main :is(", self.css)

    def test_inline_data_never_becomes_a_badge_inside_a_tab(self):
        content_contract = self.css.split(
            "Dynamic counts and labels are content inside one segment", 1
        )[1]
        self.assertIn("[data-edify-tab-count]", content_contract)
        self.assertIn("background: transparent !important;", content_contract)
        self.assertIn("color: inherit !important;", content_contract)
        self.assertIn("font: inherit !important;", content_contract)
        self.assertIn("opacity: 1 !important;", content_contract)
