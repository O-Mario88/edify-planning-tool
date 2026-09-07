"""A sub-region name on the map is a control, not a caption.

THE DEFECT THIS FIXES (owner, 2026-09-07)

"On the map, can you make sure the sub-region labels fonts are bigger and
clickable. When clicked it should only zoom out that sub-region."

The names were set at the same type step as the 135 district labels around
them, so the two levels read as one field of text, and pressing a name did
nothing — the districts beneath it had been clickable since the map was built,
and the distribution table beside it already called `focusSub()`. The name was
the one thing on the map that named a sub-region and answered to nothing.

WHAT IS FIXED HERE, AND WHY EACH PIECE

The size is set where the two levels compete and only there. Below 48rem the
map carries sub-region names ONLY (owner, 2026-09-05), so there is no second
level to be told apart from — and the same multiplier on a third of the canvas
runs WEST NILE into ACHOLI and pushes SOUTH WESTERN off the edge. Measured at
390 / 834 / 1180 / 1440px: no name leaves the canvas and no two collide.

The press reuses `focusSub()` rather than adding a second zoom path. That is
the method the distribution table has always used: it frames the sub-region's
own districts, dims the rest of the country to 0.14, and returns to the country
view when the sub-region already open is pressed again. One state machine, one
Esc, one way out.
"""

from django.test import SimpleTestCase

from .test_regional_performance_tooltip import _regional_source


class MapSubRegionLabelTest(SimpleTestCase):
    def test_a_sub_region_name_is_a_button_that_opens_its_own_sub_region(self):
        source = _regional_source()

        # Named, so the handler and the styling both have a subject.
        self.assertIn("t.dataset.sub = name;", source)
        self.assertIn("t.setAttribute('role','button');", source)
        self.assertIn("t.setAttribute('tabindex','0');", source)
        self.assertIn(
            "t.setAttribute('aria-label', `Zoom to ${name} sub-region`);",
            source,
        )

        # Pointer and keyboard reach the same method the table uses, so the
        # zoom, the dimming and Esc behave identically however it was opened.
        self.assertIn("t.addEventListener('click', event => {", source)
        self.assertIn("t.addEventListener('keydown', event => {", source)
        self.assertIn("if(event.key === 'Enter' || event.key === ' '){", source)
        # Twice and no more: the pointer handler and the keyboard one. The
        # table and the sub-county drill-up call the same method with their
        # own subject, so they do not match this exact call.
        self.assertEqual(source.count("this.focusSub(name);"), 2)

        # The press must not also reach the district under the label, which
        # would zoom to that one district instead of the sub-region.
        self.assertIn("event.stopPropagation();", source)

    def test_focus_sub_frames_one_sub_region_and_toggles_back(self):
        source = _regional_source()

        self.assertIn("focusSub(name){", source)
        # Only this sub-region's districts stay lit.
        self.assertIn("const on = p.dataset.sub === name;", source)
        self.assertIn("p.style.opacity = on ? 1 : 0.14;", source)
        # Pressing the sub-region already open returns to the country.
        self.assertIn(
            "if(this.focused === 'sub:' + name){ this.reset(); return; }",
            source,
        )

    def test_names_outrank_district_labels_except_where_they_stand_alone(self):
        source = _regional_source()

        # The heading step, and the pointer events the shared `#sr-cam text`
        # rule turns off for every other label on the map.
        self.assertIn(
            "#sr-cam .sr-sl{font-size:calc(var(--edify-svg-text-micro,"
            "var(--edify-text-micro-size)) * 1.55);",
            source,
        )
        self.assertIn("pointer-events:auto;cursor:pointer;", source)

        # Hover moves to the platform's darker step for the same accent — the
        # one every primary button uses. Measured: `--edify-primary` resolves to
        # the identical #0e5da3, so a name styled with it changed nothing under
        # the pointer and read as dead text.
        self.assertIn(
            "#sr-cam .sr-sl:focus-visible{fill:var(--edify-accent-hover);outline:none}",
            source,
        )
        self.assertNotIn("var(--edify-accent-strong", source)

        # The keyboard ring is drawn on the glyphs, not as a box: an SVG text
        # node's outline is its bounding box, which the camera magnifies on zoom.
        self.assertIn(
            "#sr-cam .sr-sl:focus-visible{stroke:var(--edify-accent);stroke-width:.3em}",
            source,
        )

        # On a phone they are the only labels, so they return to the plain step
        # rather than crowding each other off a 390px canvas.
        phone = source[source.index("@media (max-width:48rem){") :]
        phone = phone[: phone.index("#sr-cam .sr-school-pins")]
        self.assertIn("#sr-cam .sr-dl{display:none}", phone)
        self.assertIn(
            "font-size:var(--edify-svg-text-micro,var(--edify-text-micro-size))",
            phone,
        )

    def test_the_card_says_the_names_can_be_pressed(self):
        source = _regional_source()

        self.assertIn("Click a sub-region name, or a district, to zoom", source)
        self.assertIn(
            "Click a sub-region name to open it, or a district to zoom",
            source,
        )
        self.assertNotIn(">Click a district to zoom</p>", source)
