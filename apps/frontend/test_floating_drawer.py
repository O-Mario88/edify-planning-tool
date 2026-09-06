"""One drawer shape for the whole platform: a floating, always-centred card.

The owner gave a reference screenshot on 2026-09-06 — a white card floating
clear of every edge over a page that visibly steps back — and asked for that
shape everywhere, always centred, taking the design and not the contents.

Four earlier passes each re-declared `.drawer-surface` with `!important`
(a right-edge slide-over, a centred modal, a "reference-aligned floating
workspace", and an "enterprise foundation"), so the rules that decide the
drawer's shape are whichever ones come last. That makes this suite worth
having: it pins the decisions that are easy to undo by adding another block,
and the two that were outright broken before this pass.
"""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def _rule(css: str, selector: str) -> str:
    """The declarations of the LAST rule for `selector`.

    Last, because several selectors appear more than once in the final block
    (a corner-radius rule and the rule that does the work), and it is the last
    one the browser applies.
    """
    marker = selector + " {"
    start = css.rindex(marker) + len(marker)
    return css[start : css.index("}", start)]


def _without_comments(css: str) -> str:
    out = []
    rest = css
    while "/*" in rest:
        head, _, rest = rest.partition("/*")
        out.append(head)
        _, _, rest = rest.partition("*/")
    out.append(rest)
    return "".join(out)


class FloatingDrawerShapeTest(SimpleTestCase):
    def setUp(self):
        self.css = _read("static/css/drawers.css")
        # Everything this suite pins must be in the LAST block, or an earlier
        # `!important` wins and the drawer silently goes back to its old shape.
        self.final = self.css[self.css.index("THE FLOATING DRAWER") :]

    def test_the_card_is_centred_by_the_box_model_not_by_a_transform(self):
        """`inset: 0` + `margin: auto` holds the centre at any size.

        A transform-based centre has to be re-stated by every rule that wants
        to animate the drawer, which is how the platform ended up with four
        different `translate(50%, -48%)` variants.
        """
        self.assertIn("inset: 0 !important;", self.final)
        self.assertIn("margin: auto !important;", self.final)

    def test_every_drawer_type_resolves_to_the_same_card(self):
        for variant in (".drawer-surface.type-center", ".drawer-surface.type-right_top"):
            with self.subTest(variant=variant):
                self.assertIn(variant, self.final)

    def test_the_card_floats_clear_of_every_edge(self):
        self.assertIn("--edify-drawer-inset:", self.final)
        self.assertIn(
            "inline-size: calc(100% - (var(--edify-drawer-inset) * 2)) !important;",
            self.final,
        )
        self.assertIn(
            "max-block-size: calc(100dvh - (var(--edify-drawer-inset) * 2)) !important;",
            self.final,
        )

    def test_the_page_behind_steps_back(self):
        """The scrim alone reads as a grey sheet; the scale and the drained
        colour are what make it read as depth."""
        self.assertIn(".edify-drawer-recede", self.final)
        self.assertIn("filter: saturate(", self.final)
        self.assertIn("transform: scale(", self.final)

    def test_the_recede_is_driven_by_the_one_background_owner(self):
        js = _read("static/js/drawer-background.js")
        self.assertIn('var RECEDE_CLASS = "edify-drawer-recede";', js)
        self.assertIn("node.classList.add(RECEDE_CLASS);", js)
        self.assertIn("node.classList.remove(RECEDE_CLASS);", js)

    def test_no_backdrop_opts_out_of_the_scrim(self):
        """`type-right_top` used to set `background-color: transparent`, which
        left its drawer floating over an undimmed page."""
        self.assertIn(".drawer-backdrop.type-right_top,", self.final)
        self.assertIn(
            "background-color: var(--edify-drawer-scrim) !important;", self.final
        )


class DrawerFurnitureTest(SimpleTestCase):
    """The close button, the header and the action shelf."""

    def setUp(self):
        css = _read("static/css/drawers.css")
        self.final = css[css.index("THE FLOATING DRAWER") :]
        # The phone block repeats several of these selectors with only its own
        # spacing, so the rules that carry the behaviour are the last ones
        # BEFORE it.
        self.desktop = self.final[: self.final.rindex("@media (max-width: 47.99rem)")]

    def test_the_close_button_is_inside_the_card(self):
        """It was positioned at `top: -3.65rem`, i.e. floating above the panel.

        The card clips to its corners, so a close button outside it is not
        merely misplaced — it cannot be seen or clicked, and a drawer with no
        visible close is a trap.
        """
        close = _rule(self.desktop, ".drawer-surface .drawer-close-btn")
        self.assertIn("position: absolute !important;", close)
        self.assertIn("inset-block-start: 1.25rem !important;", close)
        self.assertIn("inset-inline-end: 1.25rem !important;", close)
        # The old off-panel offset survives only as prose explaining the fix.
        self.assertNotIn("top: -3.65rem", _without_comments(self.final))

    def test_the_card_scrolls_so_its_chrome_can_span_it(self):
        """With the body as the scroller, its scrollbar gutter sat inside the
        card and the action shelf stopped short of the right edge."""
        self.assertIn("overflow: hidden auto !important;", self.final)
        self.assertIn("position: sticky !important;", self.final)

    def test_the_header_is_opaque_because_it_is_sticky(self):
        """Transparent chrome over a scrolling body runs the content through
        the title."""
        header = _rule(self.desktop, ".drawer-surface .drawer-header")
        self.assertIn("position: sticky !important;", header)
        self.assertIn("background: var(--edify-surface-raised) !important;", header)
        self.assertNotIn("background: transparent", header)

    def test_the_action_shelf_pins_to_the_bottom_of_the_card(self):
        """Each drawer renders its footer inside the body block, so it is a
        child of the scrolling content rather than a flex sibling — it cannot
        be pinned by flex, and moving it in the DOM would take submit buttons
        out of the form that owns them."""
        footer = _rule(self.desktop, ".drawer-surface .drawer-footer")
        self.assertIn("position: sticky !important;", footer)
        self.assertIn("inset-block-end: 0 !important;", footer)
        self.assertIn("margin: 1.25rem -1.75rem 0 !important;", footer)


class DrawerMotionTest(SimpleTestCase):
    def setUp(self):
        css = _read("static/css/drawers.css")
        self.final = css[css.index("THE FLOATING DRAWER") :]

    def test_a_phone_gets_the_same_card_not_a_full_screen_page(self):
        self.assertIn("@media (max-width: 47.99rem)", self.final)
        self.assertIn("--edify-drawer-inset: 0.75rem;", self.final)
        # svh, so browser chrome reappearing does not resize a card mid-form.
        self.assertIn("100svh", self.final)

    def test_reduced_motion_removes_the_movement_not_the_drawer(self):
        block = self.final[self.final.index("@media (prefers-reduced-motion: reduce)") :]
        self.assertIn("transition-duration: 1ms !important;", block)
        self.assertIn("transform: none !important;", block)
