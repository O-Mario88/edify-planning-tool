"""A form that refuses to submit has to say why (owner, 2026-09-11).

"When I schedule a visit, it does not save as in the database, the save button
does nothing."

It was doing nothing, and the save that never happened was correct: a
`required` control in the drawer was empty, so the browser refused the submit.
Measured on the schedule drawer with In-school Training chosen and no training
picked: no request, no message in #form-errors, no console error. The browser
raises its own bubble, but it expires, it renders outside the document so a
scrolling drawer can carry the field away from it, and it names one field at a
time — so the planner sees a dead button.

htmx cannot report it either: native validation blocks the submit before htmx
is involved, so `htmx:validation:halted` never fires. The only signal is the
native `invalid` event, which does not bubble — hence a capture-phase listener.

These are asset-and-wiring contracts, the same shape as
test_htmx_attribute_inheritance: the behaviour itself is proven in the browser,
and what is guarded here is that the script exists, is loaded on every page,
and keeps the three properties the diagnosis turned on.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "static/js/form-refusal.js"
BASE = ROOT / "templates/base.html"


class FormRefusalScriptTest(SimpleTestCase):
    def test_the_script_ships_and_every_page_loads_it(self):
        self.assertTrue(SCRIPT.exists(), "static/js/form-refusal.js is missing")
        base = BASE.read_text(encoding="utf-8")
        self.assertIn("js/form-refusal.js", base)
        # Beside the other drawer-wide behaviour, so a drawer swapped in later
        # is covered by a listener that is already on the document.
        self.assertLess(
            base.index("js/drawer-background.js"),
            base.index("js/form-refusal.js"),
        )

    def test_it_listens_in_the_capture_phase(self):
        """`invalid` does not bubble. A listener registered without capture
        would never run, and the button would go back to doing nothing."""

        source = SCRIPT.read_text(encoding="utf-8")
        start = source.index('addEventListener(\n    "invalid"')
        # The listener's own argument list, up to the call that closes it.
        block = source[start : source.index("\n  );", start)]
        self.assertIn("true", block.rsplit(",", 1)[-1],
                      "the invalid listener must register with capture=true")

    def test_one_attempt_reports_every_missing_field_together(self):
        """The browser raises `invalid` once per rejected control in the same
        tick. Reporting each one as it arrives would overwrite the message and
        show only the last; they are gathered and rendered once."""

        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("requestAnimationFrame", source)
        self.assertIn("pending", source)

    def test_the_note_is_an_alert_and_names_the_control(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('setAttribute("role", "alert")', source)
        self.assertIn("labelFor", source)
        # It prefers the form's own error area when the page declares one, so
        # server-side and client-side refusals land in the same place.
        self.assertIn('getAttribute("hx-target")', source)
