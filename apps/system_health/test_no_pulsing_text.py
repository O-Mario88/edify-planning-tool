"""A11Y-04 — text must not sit inside an opacity animation.

`animate-pulse` animates opacity between 1 and about 0.5. On a decorative dot
that is harmless: there is nothing to read. On an element carrying text it
means the text's contrast against what is behind it changes continuously, and
for roughly half of every two-second cycle it is below the AA threshold.

HOW THIS WAS FOUND, because the symptom looked like something else entirely

`scripts/accessibility_audit.py` reported the /notifications page failing, then
passing, then failing, on the same code against the same data: 3 blocking
violations, then 1, then 0, then 2. A count that moves while nothing moves is
not a flaky tool — it is a measurement of something that varies. axe samples
one instant, and the badge it was sampling was mid-pulse.

Measured directly, the badge's opacity over one cycle:

    1.000  0.976  0.869  0.722  0.587  0.511  0.507  0.577  0.708  0.964

Two rounds of "fixing" the colour went in before that was understood — first
darkening the fill, then correcting a class that was not in the compiled
bundle. Both were real improvements at peak opacity. Neither could fix the
trough, because the trough is not a colour problem.

THE RULE

An element that carries text must not carry `animate-pulse`. Every other use
in this codebase is already a bare dot — 14 of them, `h-1.5 w-1.5` and similar,
with no text node inside. Only two elements ever broke it: the /notifications
"Action Required" badge, and a "Live" badge on the admin index that no scanned
page reaches, so no audit would ever have caught it. That second one is the
reason this is a test over the templates rather than a note in the audit's
baseline: the audit scans eight pages, and the defect does not respect that
boundary.

This is also WCAG 2.2.2 territory — content that moves indefinitely with no
way to pause it — but contrast is the part that is measurable here, so
contrast is what this asserts.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATES = Path(settings.BASE_DIR) / "templates"

#: An opening tag carrying the class, through to its matching close. Kept to
#: the elements that actually hold text; a pulsing <svg> or <img> is not what
#: this is about.
PULSING = re.compile(
    r"<(?P<tag>span|div|p|a|button|li|strong|em|h[1-6])\b[^>]*"
    r"\banimate-pulse\b[^>]*>(?P<body>.*?)</(?P=tag)>",
    re.S,
)

#: Strips markup so the question is "is there text here", not "is there
#: anything here". A nested decorative <span> inside a pulsing wrapper still
#: leaves the wrapper text-free.
MARKUP = re.compile(r"<[^>]+>")


def _pulsing_text_elements() -> list[str]:
    offenders: list[str] = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        for match in PULSING.finditer(source):
            body = MARKUP.sub("", match.group("body")).strip()
            if not body:
                continue
            line = source[: match.start()].count("\n") + 1
            offenders.append(
                f"{path.relative_to(settings.BASE_DIR)}:{line} -> {body[:60]!r}"
            )
    return offenders


class NoPulsingTextTest(SimpleTestCase):
    def test_no_text_sits_inside_a_pulse_animation(self):
        offenders = _pulsing_text_elements()
        self.assertEqual(
            offenders,
            [],
            "these elements animate their opacity while carrying text, so "
            "their contrast drops below AA for about half of every cycle and "
            "an accessibility scan will report them intermittently:\n  "
            + "\n  ".join(offenders)
            + "\n\nDrop `animate-pulse` from the element. If the intent is to "
            "draw attention, animate something that is not the text — a ring "
            "or a sibling dot, as the other fourteen uses in this codebase "
            "already do.",
        )

    def test_the_scan_actually_finds_pulsing_elements(self):
        """Otherwise the rule above passes because the pattern stopped matching.

        The regex depends on the class name and on tags being closed the way
        they are written today. If a refactor renames the utility or the
        scanner silently matches nothing, the assertion above becomes a
        statement about an empty set — which is exactly the failure mode this
        audit has hit repeatedly. So assert the scanner still sees the
        decorative uses it is supposed to skip.
        """
        seen = 0
        for path in TEMPLATES.rglob("*.html"):
            seen += len(PULSING.findall(path.read_text(encoding="utf-8")))
        self.assertGreaterEqual(
            seen,
            10,
            f"the scanner matched only {seen} animate-pulse elements. This "
            f"codebase has around fourteen decorative ones; a number this low "
            f"means the pattern has stopped matching and the rule above is "
            f"guarding nothing.",
        )
