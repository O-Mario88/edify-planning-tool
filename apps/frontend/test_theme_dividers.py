"""Contrast contracts for night surfaces and decorative separators."""

import re
from pathlib import Path
from django.test import SimpleTestCase
from apps.frontend.test_design_system_quality import _contrast_ratio


def _theme_tokens(css: str, selector: str) -> dict[str, str]:
    block = r"^" + re.escape(selector) + r"\s*\{(.*?)\n\}"
    body = re.search(block, css, re.S | re.M)[1]
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body))


class HoverMatchesQuickAccessTests(SimpleTestCase):
    """Owner, 2026-10-23: Home's Quick access hover, platform-wide."""

    css = Path("static/css/design-system.css").read_text()

    def test_light_hover_is_the_quick_access_blue(self):
        tokens = _theme_tokens(self.css, ":root")
        self.assertEqual(tokens["--edify-surface-hover"], "var(--brand-primary-soft)")
        self.assertEqual(
            tokens["--edify-table-row-hover"], "var(--edify-surface-hover)"
        )
        home = Path("static/css/pages/home.css").read_text()
        self.assertIn(
            ".edify-home__shortcut:hover {\n  background: var(--brand-primary-soft);",
            home,
        )

    def test_night_hover_is_lighter_than_every_surface_it_lands_on(self):
        # A hover at or under a surface's own lightness disappears on it: a
        # menu (popover) or a raised card would not answer the pointer.
        for theme in ("blue", "dark"):
            tokens = _theme_tokens(self.css, f":root.theme-{theme}")
            hover = tokens["--edify-surface-hover"]
            for surface in (
                "--edify-surface",
                "--edify-surface-muted",
                "--edify-surface-raised",
                "--edify-surface-popover",
            ):
                with self.subTest(theme=theme, surface=surface):
                    self.assertGreater(
                        _contrast_ratio(hover, "#000000"),
                        _contrast_ratio(tokens[surface], "#000000"),
                    )
            with self.subTest(theme=theme, token="row"):
                self.assertEqual(
                    tokens["--edify-table-row-hover"], "var(--edify-surface-hover)"
                )


class ThemeDividerTests(SimpleTestCase):
    def test_each_dark_theme_defines_quiet_dividers_and_readable_accents(self):
        css = Path("static/css/design-system.css").read_text()
        for theme in ("blue", "dark"):
            body = re.search(r":root\.theme-" + theme + r"\s*\{(.*?)\n\}", css, re.S)[1]
            tokens = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body))
            with self.subTest(theme=theme):
                surface = tokens["--edify-surface"]
                divider = tokens["--edify-divider"]
                self.assertLess(_contrast_ratio(divider, surface), 2)
                self.assertGreaterEqual(
                    _contrast_ratio(tokens["--edify-accent-text"], surface), 4.5
                )
                control = tokens["--edify-control-border"]
                if control.startswith("var("):
                    control = tokens[control[4:-1]]
                self.assertGreaterEqual(_contrast_ratio(control, surface), 3)
                for token in (
                    "--edify-surface-hover",
                    "--edify-surface-selected",
                    "--edify-text-disabled",
                ):
                    self.assertIn(token, tokens)
