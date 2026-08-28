"""A11Y-01 — the accessibility ratchet has to stay a ratchet.

`scripts/accessibility_audit.py` drives a real browser, signs in, and runs
axe-core over the pages people use. It needs Chromium and a seeded estate, so
like `scripts/latency_budget.py` it is run deliberately rather than on every
commit. What *is* checked on every commit is the thing that would quietly undo
it: the baseline file.

A ratchet fails in one direction only if nobody edits the numbers. Three ways
this one could stop meaning anything, none of which any other test would
notice:

* the file is deleted — the audit then reports "no baseline" for every page,
  which reads like a fresh start rather than a lost gate;
* a page is dropped from it — that page's violations stop being compared to
  anything;
* a count is raised to absorb a new violation instead of the violation being
  fixed — the number goes up, the gate goes green, and the regression ships.

The first two are asserted here. The third cannot be caught by a test, because
a legitimately raised number and an illegitimately raised one look identical in
the file — so it is a review rule, written on the file itself and repeated in
the audit's own output.

The measured state at the time of writing: **zero** serious or critical
violations across all eight pages, after A11Y-01 fixed six real colour-contrast
failures on the KPI tiles. Zero is therefore the ratchet, and any new violation
fails on the day it is introduced.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASELINE = Path(settings.BASE_DIR) / "docs" / "accessibility-baseline.json"
AUDIT = Path(settings.BASE_DIR) / "scripts" / "accessibility_audit.py"


def _tuple_from(source: str, name: str) -> list[str]:
    block = source.split(f"{name} = (", 1)[1].split(")", 1)[0]
    return [
        part.strip().strip(",").strip('"')
        for part in block.replace("\n", " ").split(",")
        if part.strip().strip(",").strip('"')
    ]


def _keys_the_audit_scans() -> list[str]:
    """Every `theme:page` the audit covers, read from its own source.

    Read rather than duplicated. A copy of either list here would drift from
    the one that matters, and the drift would be invisible: this test would
    keep passing about combinations the audit had stopped scanning.

    Themes matter as much as pages. Colour contrast is most of what axe checks
    and is entirely a property of the palette, so a clean light theme says
    nothing about the other two — this project ships three, and DARK-01
    established that its dark theme has carried real contrast failures before.
    """
    source = AUDIT.read_text(encoding="utf-8")
    pages = _tuple_from(source, "DEFAULT_PAGES")
    themes = _tuple_from(source, "THEMES")
    return [f"{theme}:{page}" for theme in themes for page in pages]


class AccessibilityBaselineTest(SimpleTestCase):
    def test_the_baseline_exists(self):
        self.assertTrue(
            BASELINE.exists(),
            f"{BASELINE.name} is missing. Without it every page reports "
            f"'no baseline' and the accessibility ratchet is off. Regenerate "
            f"with A11Y_WRITE_BASELINE=1 scripts/accessibility_audit.py — but "
            f"only after checking the numbers it writes are the ones you meant.",
        )

    def test_it_covers_every_theme_and_page_the_audit_scans(self):
        recorded = json.loads(BASELINE.read_text(encoding="utf-8"))["pages"]
        scanned = _keys_the_audit_scans()
        self.assertTrue(scanned, "parsed no theme/page pairs out of the audit")
        self.assertEqual(
            sorted(recorded),
            sorted(scanned),
            "the baseline and the audit disagree about what is covered. A "
            "combination in the audit but not the baseline is ungated; one in "
            "the baseline but not the audit is a stale entry hiding the fact "
            "that nothing scans it any more. Dropping a whole THEME is the "
            "quiet way to lose two thirds of this gate.",
        )

    def test_every_theme_is_actually_represented(self):
        """A baseline covering one theme three times would satisfy the check
        above only if the audit also dropped to one theme — which is exactly
        the regression worth naming separately."""
        recorded = json.loads(BASELINE.read_text(encoding="utf-8"))["pages"]
        themes = {key.split(":", 1)[0] for key in recorded}
        self.assertGreaterEqual(
            len(themes),
            3,
            f"the baseline covers only {sorted(themes)}. This product ships "
            f"light, dark and blue, and contrast is a property of the palette.",
        )

    def test_the_counts_are_the_measured_zero(self):
        """Not a style preference — the measured state, asserted.

        Six colour-contrast failures were fixed rather than recorded, so the
        honest baseline is zero. Writing that down is what makes the next
        violation fail instead of blending into an allowance.
        """
        recorded = json.loads(BASELINE.read_text(encoding="utf-8"))["pages"]
        offenders = {page: n for page, n in recorded.items() if n != 0}
        self.assertEqual(
            offenders,
            {},
            f"the baseline allows {sum(offenders.values())} serious/critical "
            f"violation(s) on {sorted(offenders)}. If those were fixed, lower "
            f"it. If they were newly introduced, the fix is the violation, "
            f"not the number.",
        )

    def test_the_file_says_it_is_a_ratchet(self):
        """The rule travels with the file, for whoever regenerates it next."""
        text = BASELINE.read_text(encoding="utf-8")
        self.assertIn("RATCHET", text)
        self.assertIn("never to absorb new ones", text)
