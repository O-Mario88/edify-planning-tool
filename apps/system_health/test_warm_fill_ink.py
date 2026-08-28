"""A11Y-03 — constant dark ink belongs only on fills that stay light.

`consistency.css` pins a constant dark ink on the warm Tailwind fills:

    main [class*="bg-amber-"]... { color: var(--edify-on-warm-fill) !important }

The reasoning in that rule is sound and its comment states it: `bg-amber-400`
is amber-400 in every theme, so near-white on it measures 1.53:1 and the ink
has to be dark and constant.

The premise is false for the PALE tints. `components.css` and `custom.css` both
remap `.dark .bg-amber-50` (and its siblings) to a dark translucent brown,
because a near-white tint would glare in a dark theme. A constant dark ink on a
background that turns dark leaves dark on dark: the /notifications amber badge
measured **#17232b on #332e21, a ratio of 1.18:1** against a required 4.5 —
not low contrast but invisible text. axe reported three serious violations in
the dark theme and one in light against a baseline of zero, and it reproduced
identically on a clean checkout of `main`, so it shipped that way.

`bg-amber-50` appears about 190 times across the templates. This was never one
badge on one page.

WHAT THIS TEST IS FOR

The fix excludes the theme-flipped tints from the constant-ink rule. That
exclusion is only correct while the two lists agree, and they are written in
different files by different people for different reasons:

* whichever sheet adds `.dark .bg-<colour>-<n>` decides that a tint flips;
* `consistency.css` decides which tints keep the constant ink.

Nothing connects them. Add a remap for `.dark .bg-lime-50` tomorrow and the
same invisible-text defect returns, in a place nobody is looking, and no test
would notice — which is exactly how this one survived. So this test derives the
required exclusions from the remaps themselves and fails when they diverge.

It does not check contrast. Contrast is axe-core's job, in
`scripts/accessibility_audit.py`, which implements colour spaces properly;
this session got hand-rolled oklch conversion wrong twice before deferring to
it. What this checks is the structural invariant that makes the contrast right.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

CSS = Path(settings.BASE_DIR) / "static" / "css"
CONSISTENCY = CSS / "consistency.css"

#: The families the constant-ink rule covers.
WARM = ("amber", "yellow", "orange", "lime")

#: A tint is "pale" if it is light enough that a dark theme would want to
#: replace it rather than keep it. In Tailwind's scale that is 50 and 100;
#: 200 and above are already saturated enough to carry dark ink in any theme,
#: and none of them are remapped.
PALE = ("50", "100")

REMAP = re.compile(
    r"\.dark\s+\.bg-(" + "|".join(WARM) + r")-(\d+)\b",
)


def _remapped_tints() -> set[tuple[str, str]]:
    """Every warm background some sheet flips under the dark theme."""
    found: set[tuple[str, str]] = set()
    for sheet in sorted(CSS.rglob("*.css")):
        for colour, step in REMAP.findall(sheet.read_text(encoding="utf-8")):
            found.add((colour, step))
    return found


def _warm_ink_rule() -> str:
    """The selector of the constant-ink rule, read from the sheet itself."""
    text = CONSISTENCY.read_text(encoding="utf-8")
    marker = "var(--edify-on-warm-fill) !important"
    index = text.find(marker)
    if index == -1:
        return ""
    # Walk back to the start of the selector list.
    start = text.rfind("}", 0, index)
    start = text.rfind("*/", 0, index) if start == -1 else start
    return text[start + 1 : text.find("{", index - 400) + 1]


class WarmFillInkTest(SimpleTestCase):
    def test_the_rule_still_exists(self):
        """If it is gone, every assertion below passes about nothing."""
        self.assertIn(
            "--edify-on-warm-fill",
            CONSISTENCY.read_text(encoding="utf-8"),
            "the constant warm-fill ink rule has been removed from "
            "consistency.css. It exists because near-white on amber-400 "
            "measures 1.53:1; deleting it brings that back.",
        )

    def test_some_warm_tints_really_are_remapped_for_dark(self):
        """The premise this whole test rests on, asserted rather than assumed.

        If no sheet remapped any warm tint, the exclusions below would be
        unnecessary and this file would be guarding a rule that no longer has
        the problem — worth knowing, and worth failing over, because it would
        mean the dark theme had stopped adapting these tints at all.
        """
        remapped = _remapped_tints()
        self.assertTrue(
            remapped,
            "no sheet remaps any warm background under .dark any more. Either "
            "the dark theme stopped adapting these tints — which is its own "
            "defect — or the selectors changed shape and this test has gone "
            "blind.",
        )

    def test_every_dark_remapped_tint_is_excluded_from_the_constant_ink(self):
        """The invariant. Two files, no link between them, until this.

        A tint that a dark theme turns dark must NOT also be pinned to a
        constant dark ink, or its text disappears. Whichever sheet adds the
        remap is where the risk enters; this is where it is caught.
        """
        rule = _warm_ink_rule()
        self.assertTrue(rule, "could not read the warm-ink selector")
        missing = []
        for colour, step in sorted(_remapped_tints()):
            if step not in PALE:
                # A saturated step that is nonetheless remapped is a different
                # question, and naming it here rather than ignoring it keeps
                # this from silently passing over a case nobody considered.
                missing.append(
                    f"bg-{colour}-{step} is remapped for dark but is not a "
                    f"pale tint; decide deliberately what ink it should take"
                )
                continue
            token = f'[class~="bg-{colour}-{step}"]'
            if f":not({token})" not in rule:
                missing.append(
                    f"bg-{colour}-{step} flips to a dark background under "
                    f".dark but still takes the constant dark ink"
                )
        self.assertEqual(
            missing,
            [],
            "these warm tints turn dark in the dark theme AND carry a "
            "constant dark ink, which is invisible text:\n  "
            + "\n  ".join(missing)
            + '\n\nAdd the matching :not([class~="..."]) exclusions to the '
            "warm-fill ink rule in consistency.css.",
        )

    def test_the_exclusions_use_token_matching_not_substrings(self):
        """`[class*="bg-amber-50"]` also matches `bg-amber-500`.

        Excluding with a substring would remove the ink from the saturated
        fill this rule exists to keep legible — undoing the fix as part of
        applying it. `~=` matches a whole class token, so it cannot.
        """
        rule = _warm_ink_rule()
        for colour in WARM:
            for step in PALE:
                bad = f'[class*="bg-{colour}-{step}"]'
                self.assertNotIn(
                    f":not({bad})",
                    rule,
                    f"{bad} is a substring test: it also matches "
                    f"bg-{colour}-{step}0, a saturated fill that must keep "
                    f'the dark ink. Use [class~="bg-{colour}-{step}"] instead.',
                )
