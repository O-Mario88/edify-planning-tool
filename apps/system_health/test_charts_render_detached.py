"""FREEZE-01 — every chart must be built outside the document.

`EdifyChartSystem.renderDetached` exists because ApexCharts sizes its text by
appending an element and reading its geometry back, about ninety times per
render. That read flushes pending style, and a style flush inside `<main>` on
this application costs 87.9ms on /analytics against 0.10ms outside it — the
page ships ~11,000 selectors across 17 stylesheets, ~650 of them built from
:is()/:where() chains rooted at `main`, which cannot be indexed per element.

Ninety flushes at 87.9ms is the six-second freeze. Building the chart in a
detached subtree and attaching it once makes those ninety flushes free, because
a detached subtree has no document styles to resolve against:

    attached (as it was)   8041ms
    detached + attached     112ms      identical output — 3 series, 24 bars,
                                       12 x-axis labels, 697x240

WHY A TEST AND NOT A COMMENT

The fix lives at twenty-one call sites across a dozen templates. Nothing about
`new ApexCharts(el, cfg); chart.render()` looks wrong — it is what every
tutorial and every one of those call sites said until this change, and it is
what the next person will write. One reintroduced call site brings back a
multi-second freeze on that page, and no other test would notice: the chart
still renders, the page still passes, it is just unusable while it does.

So the rule is asserted where it can fail: no template and no application
script may construct an ApexCharts directly. The single exception is the helper
itself, which has to.

WHAT THIS DOES NOT CLAIM

It does not claim the pages are fast. The underlying defect — a stylesheet
whose selectors make any mutation under `<main>` cost a document-wide style
recalculation — is untouched by this, and is gated separately by
`test_style_recalc_baseline`. This asserts only that the chart path no longer
walks into it ninety times.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)

#: The helper's own construction, and nothing else. Held as a path so a file
#: renamed out from under this test fails loudly rather than widening the
#: exemption to whatever is there now.
HELPER = BASE / "templates" / "base.html"

CONSTRUCTION = re.compile(r"new\s+ApexCharts\s*\(")
DETACHED = re.compile(r"EdifyChartSystem\.renderDetached\s*\(")


def _sources():
    """Every template and first-party script that could build a chart.

    `static/js/vendor/` is excluded: ApexCharts' own minified source obviously
    constructs itself, and reading it here would be noise. Nothing else is
    excluded, because anywhere else is somewhere a call site could hide.
    """
    for path in sorted(BASE.glob("templates/**/*.html")):
        yield path
    for path in sorted(BASE.glob("static/js/**/*.js")):
        if "vendor" in path.parts:
            continue
        yield path


class ChartsRenderDetachedTest(SimpleTestCase):
    def test_the_helper_exists(self):
        """If the helper is gone the rule below passes vacuously."""
        text = HELPER.read_text(encoding="utf-8")
        self.assertIn(
            "renderDetached: function",
            text,
            f"{HELPER.name} no longer defines renderDetached. Every call site "
            f"below calls it; without it, no chart renders at all.",
        )

    def test_the_helper_stages_outside_main_at_the_slot_width(self):
        """The three properties the speed and the correctness both rest on.

        It stages under `<body>`, which is the whole point: `main :is(...)`
        selectors cannot match there, so the ninety flushes are free. It
        measures the real slot first and gives the stage that width, because a
        chart drawn at the wrong width is fast and wrong. And it falls back to
        rendering in place when the slot cannot be measured — a hidden panel, a
        collapsed drawer — because slow and correct beats fast and wrong.

        Staging under `<body>` rather than fully detached is deliberate: a
        detached element has no layout, so the width would have to be a fixed
        number, which disables ApexCharts' own resize handling and invites a
        replacement that re-renders attached — this defect again, on every
        window drag.
        """
        text = HELPER.read_text(encoding="utf-8")
        self.assertIn(
            "document.body.appendChild(holder)",
            text,
            "the helper no longer stages under <body>. If it stages inside "
            "<main> the render pays a document-wide style recalculation per "
            "measurement, which is the freeze this exists to remove.",
        )
        self.assertIn("getBoundingClientRect", text)
        self.assertIn("stage.style.width = slot", text)
        self.assertIn(
            "inPlace.render()",
            text,
            "the unmeasurable-slot fallback is gone. Without it a chart in a "
            "hidden panel renders at zero width — fast, and wrong.",
        )

    def test_the_helper_clears_its_own_previous_stage(self):
        """Otherwise every re-render leaves an empty div behind.

        Call sites re-render by calling `destroy()` and then the helper again —
        a theme change, a filter, a period switch. `destroy()` tears down
        ApexCharts' own DOM and knows nothing about the holder the helper
        added, so the first version of this leaked one div per re-render:
        measured at 2 -> 6 children over five re-renders, which is DOM growth
        on a repeated user action, the exact shape `freeze_hunt` exists to
        catch. After the fix it is 1 -> 1.

        The holder is removed by its own marker rather than by clearing the
        slot, so content the caller owns is not destroyed along with it.
        """
        text = HELPER.read_text(encoding="utf-8")
        self.assertIn(
            "data-edify-chart-stage",
            text,
            "the helper no longer marks the container it adds, so it cannot "
            "tell its own leftovers from the caller's content and can only "
            "either leak or over-delete.",
        )
        self.assertIn(
            "previous.remove()",
            text,
            "nothing removes the previous stage, so every re-render leaves an "
            "empty div in the slot.",
        )

    def test_no_call_site_constructs_a_chart_directly(self):
        offenders = []
        for path in _sources():
            if path == HELPER:
                continue
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), start=1):
                if CONSTRUCTION.search(line):
                    offenders.append(f"{path.relative_to(BASE)}:{number}")
        self.assertEqual(
            offenders,
            [],
            "these call sites build an ApexCharts directly, which renders it "
            "attached to the document and pays a document-wide style "
            "recalculation on each of ~90 internal measurements:\n  "
            + "\n  ".join(offenders)
            + "\n\nUse window.EdifyChartSystem.renderDetached(el, options) "
            "instead. It returns the chart synchronously, so a caller holding "
            "it for destroy() needs no other change.",
        )

    def test_the_call_sites_are_actually_there(self):
        """The rule above is satisfied by a codebase with no charts at all.

        Twenty-one call sites were converted. Asserting they still call the
        helper is what stops this suite going green because charts were
        quietly deleted rather than fixed.
        """
        found = 0
        for path in _sources():
            if path == HELPER:
                continue
            found += len(DETACHED.findall(path.read_text(encoding="utf-8")))
        self.assertGreaterEqual(
            found,
            21,
            f"only {found} call sites use renderDetached, and 21 were "
            f"converted. Either charts were removed, or a call site went back "
            f"to constructing one directly by a route the pattern above misses.",
        )
