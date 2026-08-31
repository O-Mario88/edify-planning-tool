"""FREEZE-01 — keep the style-recalculation ratchet a ratchet.

`scripts/style_recalc_audit.py` drives a real browser, signs in, and measures
what one DOM mutation inside `<main>` costs on each page. Like the accessibility
audit and the latency budget it needs Chromium and a seeded estate, so it is run
deliberately rather than on every commit. What *is* checked on every commit is
the thing that would quietly undo it: the baseline file.

The three ways this gate could stop meaning anything, none of which any other
test would notice:

* the file is deleted — every page then reports "no baseline", which reads as a
  fresh start rather than a lost gate;
* a page is dropped from it — that page's cost stops being compared to
  anything, and `/analytics` is precisely the page someone would drop;
* a number is raised to absorb a regression instead of the regression being
  fixed — the page gets slower, the gate goes green, and the freeze ships.

The first two are asserted here. The third cannot be caught by a test, because
a legitimately lowered number and an illegitimately raised one look identical
in the file — so it is a review rule, written on the file itself and repeated
in the audit's own output.

WHAT THE NUMBERS MEAN, so nobody has to rediscover it

The measured state at the time of writing: appending one element inside
`<main>` and reading its geometry costs **87.9ms on /analytics**, 39.9ms on
/schools and 39.4ms on /system-health, against 0.5ms on /dashboard and 0.2ms
anywhere outside `<main>`. The budget is 16ms — one frame — because components
mutate and measure in loops: ApexCharts does about ninety such cycles while it
renders, which is how 87.9ms becomes the six-second freeze that Chromium's own
counters attribute to style recalculation (6,245ms, 49% of wall clock, against
298ms of layout).

So these are not "slow pages". They are pages where any looping interaction
stops answering, and this file is the record of that staying true or not.

THIS TEST DOES NOT CLOSE FREEZE-01

It pins the measurement so the defect cannot silently get worse or silently
disappear. Three pages are over budget and the defect stays open until they are
under it. A committed baseline is evidence of a measurement, never of a fix.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASELINE = Path(settings.BASE_DIR) / "docs" / "style-recalc-baseline.json"
AUDIT = Path(settings.BASE_DIR) / "scripts" / "style_recalc_audit.py"


def _tuple_from(source: str, name: str) -> list[str]:
    block = source.split(f"{name} = (", 1)[1].split(")", 1)[0]
    return [
        part.strip().strip(",").strip('"')
        for part in block.replace("\n", " ").split(",")
        if part.strip().strip(",").strip('"')
    ]


def _pages_the_audit_scans() -> list[str]:
    """Read from the audit's own source rather than duplicated here.

    A copy of the list in this file would drift from the one that matters, and
    the drift would be invisible: this test would keep passing about pages the
    audit had stopped measuring.
    """
    return _tuple_from(AUDIT.read_text(encoding="utf-8"), "DEFAULT_PAGES")


def _baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


class StyleRecalcBaselineTest(SimpleTestCase):
    def test_the_baseline_exists(self):
        self.assertTrue(
            BASELINE.exists(),
            f"{BASELINE.name} is missing. Without it every page reports 'no "
            f"baseline' and FREEZE-01 is ungated. Regenerate with "
            f"STYLE_WRITE_BASELINE=1 scripts/style_recalc_audit.py — but only "
            f"after checking the numbers it writes are the ones you meant.",
        )

    def test_it_covers_every_page_the_audit_scans(self):
        recorded = _baseline()["pages"]
        scanned = _pages_the_audit_scans()
        self.assertTrue(scanned, "parsed no pages out of the audit")
        self.assertEqual(
            sorted(recorded),
            sorted(scanned),
            "the baseline and the audit disagree about what is covered. A page "
            "in the audit but not the baseline is ungated; one in the baseline "
            "but not the audit is a stale entry hiding the fact that nothing "
            "measures it any more. Dropping /analytics — the worst page — is "
            "the quiet way to make this gate look clean.",
        )

    def test_the_budget_is_one_frame(self):
        """16ms is not a preference. It is the frame, and the reason the
        number matters: a mutation dearer than a frame drops one, and these
        mutations happen in loops."""
        self.assertEqual(
            _baseline()["budget_ms"],
            16.0,
            "the budget moved. It is one frame at 60Hz; raising it does not "
            "make the pages faster, it makes the freeze allowed.",
        )

    def test_the_pages_over_budget_are_still_named_as_defects(self):
        """FREEZE-01 is open, and this asserts it is still recorded as open.

        If someone genuinely fixes these pages, this test fails and should be
        deleted along with the defect. That is the intended way for it to go:
        loudly, with the numbers in front of whoever changed them. What it
        stops is the other way — the numbers being raised until nothing is
        over budget and the freeze becoming the baseline.
        """
        recorded = _baseline()["pages"]
        budget = _baseline()["budget_ms"]
        over = {page: ms for page, ms in recorded.items() if ms > budget}
        self.assertEqual(
            sorted(over),
            ["/analytics", "/schools", "/system-health"],
            f"the set of pages over the {budget}ms budget changed to "
            f"{sorted(over)}. If a page was fixed, delete it from this list "
            f"and say so. If a page newly went over, that is a regression and "
            f"the fix is the page, not this list.",
        )

    def test_analytics_is_recorded_as_the_worst_page(self):
        """The one page whose number drove the whole diagnosis.

        87.9ms per mutation, about ninety mutations in a chart render, is the
        six-second freeze. If this stops being the worst page, either it was
        fixed or something else regressed past it — both are worth stopping
        for.
        """
        recorded = _baseline()["pages"]
        worst = max(recorded, key=lambda page: recorded[page])
        self.assertEqual(
            worst,
            "/analytics",
            f"{worst} is now the worst page at {recorded[worst]}ms, not "
            f"/analytics at {recorded.get('/analytics')}ms.",
        )

    def test_the_file_says_it_is_a_ratchet(self):
        """The rule travels with the file, for whoever regenerates it next."""
        text = BASELINE.read_text(encoding="utf-8")
        self.assertIn("RATCHET", text)
        self.assertIn("never to absorb", text)
