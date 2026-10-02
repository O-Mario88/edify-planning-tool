"""Type sizes and corner radii come from the token scale (2026-10-01).

The audit of that date measured what 150 pages actually render: 26 different
font sizes and 20 corner radii, against a scale of seven type steps and five
radii. The stragglers — 12.8px, 13.44px, 14.47px, 20.48px, 7px, 9px, 13px —
were all the same thing: a stylesheet writing `font-size: 0.84rem` or
`border-radius: 9px` beside a token that already said almost that.

This is a ratchet, not a ban. Each ceiling is the number of literal
declarations left in the source stylesheets after that clean-up; a change may
lower a count and its ceiling, never raise one. A new rule takes
`var(--edify-text-…-size)` or `var(--edify-radius-…)`
(static/css/design-system.css). A value the scale genuinely lacks is a
conversation about the scale, not a one-off number.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "static" / "css"

#: Generated bundles and third-party sheets are not ours to count.
SKIPPED_NAMES = {"main.css", "tokens.css"}

#: Values that are not a size of their own: they inherit, or fill, or reset.
NEUTRAL = {"inherit", "initial", "unset", "1em", "100%", "0", "50%"}

#: Literal declarations left after the 2026-10-02 clean-up, which moved every
#: plain size up to 28px and every plain radius onto a token. What remains is
#: fluid display type (clamp(...) on heroes and the sign-in page), figures
#: larger than the display step, form fields that stay 16px so a phone does not
#: zoom on focus, the sign-in page's own composition (login.css, which is pinned
#: by its own tests), and three radii that are shapes rather than steps. Lower these when a change removes some; never raise them.
FONT_SIZE_CEILING = 69
RADIUS_CEILING = 3

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _literals(prop: str) -> Counter:
    """Literal `prop` declarations per source stylesheet."""
    pattern = re.compile(prop + r"\s*:\s*([^;}{]+)")
    found: Counter = Counter()
    for sheet in sorted(SOURCE.rglob("*.css")):
        if "vendor" in sheet.parts or sheet.name in SKIPPED_NAMES:
            continue
        css = _COMMENT.sub("", sheet.read_text())
        for match in pattern.finditer(css):
            value = match.group(1).replace("!important", "").strip()
            if "var(" in value or value in NEUTRAL:
                continue
            found[str(sheet.relative_to(ROOT))] += 1
    return found


def _report(found: Counter) -> str:
    return "\n".join(f"  {count:>4}  {name}" for name, count in found.most_common(12))


class DesignTokenRatchetTests(TestCase):
    def test_font_sizes_outside_the_scale_do_not_grow(self):
        found = _literals("font-size")
        total = sum(found.values())
        self.assertLessEqual(
            total,
            FONT_SIZE_CEILING,
            f"{total} literal font sizes, ceiling {FONT_SIZE_CEILING}. Use a "
            f"--edify-text-*-size token.\n{_report(found)}",
        )

    def test_radii_outside_the_scale_do_not_grow(self):
        found = _literals("border-radius")
        total = sum(found.values())
        self.assertLessEqual(
            total,
            RADIUS_CEILING,
            f"{total} literal radii, ceiling {RADIUS_CEILING}. Use a "
            f"--edify-radius-* token.\n{_report(found)}",
        )

    def test_the_ceilings_are_kept_tight(self):
        """A ceiling left far above the count stops guarding anything."""
        for prop, ceiling in (
            ("font-size", FONT_SIZE_CEILING),
            ("border-radius", RADIUS_CEILING),
        ):
            total = sum(_literals(prop).values())
            self.assertGreaterEqual(
                total,
                ceiling - 15,
                f"{prop}: {total} literals but the ceiling is {ceiling}; "
                "lower the ceiling to the new count.",
            )
