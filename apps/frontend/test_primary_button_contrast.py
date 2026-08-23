"""A primary button's label has to survive its own hover.

Dark mode's primary fill is #e9eef8 and its hover is #ffffff, because on a
dark page the LIGHT button is the prominent one. The ink was hard-coded white
for every theme, so on hover the label was the same colour as the button it
sat on — 1.00:1, invisible. Each theme already declared the right ink as
--text-on-brand; the accent tokens simply were not using it.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]

#: WCAG 2.2 AA for normal-size text.
AA_NORMAL = 4.5


def _luminance(hex_colour: str) -> float:
    value = hex_colour.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class PrimaryButtonInkTest(SimpleTestCase):
    def _tokens(self) -> str:
        return (ROOT / "static" / "css" / "design-system.css").read_text()

    def test_the_accent_ink_is_the_theme_s_own_rather_than_always_white(self):
        tokens = self._tokens()

        # Hard-coding one side of a fill/ink pair is what broke this: the
        # fill moved per theme and the ink did not follow it.
        self.assertNotIn("--edify-on-accent: #ffffff;", tokens)
        self.assertIn("--edify-on-accent: var(--text-on-brand, #ffffff);", tokens)

    def test_the_solid_button_ink_follows_the_same_rule(self):
        tokens = self._tokens()

        self.assertNotIn("--brand-primary-on-solid: #ffffff;", tokens)
        self.assertIn(
            "--brand-primary-on-solid: var(--text-on-brand, #ffffff);", tokens
        )

    def test_every_theme_declares_an_ink_for_its_brand(self):
        # The fallback exists, but a theme that overrides the fill and forgets
        # the ink is exactly the failure being guarded against.
        custom = (ROOT / "static" / "css" / "custom.css").read_text()
        fills = len(re.findall(r"--brand-primary:\s*#", custom))
        inks = len(re.findall(r"--text-on-brand:\s*#", custom))

        self.assertGreaterEqual(
            inks,
            fills,
            "a theme overrides --brand-primary without declaring the ink that "
            "goes on it",
        )

    def test_each_theme_s_declared_pair_is_readable(self):
        """The measured contrast of every fill against the ink beside it."""
        custom = (ROOT / "static" / "css" / "custom.css").read_text()

        # Blocks are ordered; pair each --brand-primary* fill with the
        # --text-on-brand declared in the same block.
        blocks = custom.split("--text-on-brand:")
        failures = []
        for block in blocks[1:]:
            ink = re.match(r"\s*(#[0-9a-fA-F]{6})", block)
            if not ink:
                continue
            ink_hex = ink.group(1)
            for name in ("--brand-primary", "--brand-primary-hover"):
                found = re.search(rf"{name}:\s*(#[0-9a-fA-F]{{6}})", block)
                if not found:
                    continue
                ratio = contrast(ink_hex, found.group(1))
                if ratio < AA_NORMAL:
                    failures.append(
                        f"{name} {found.group(1)} on ink {ink_hex}: {ratio:.2f}:1"
                    )

        self.assertEqual(failures, [], f"unreadable primary buttons: {failures}")
