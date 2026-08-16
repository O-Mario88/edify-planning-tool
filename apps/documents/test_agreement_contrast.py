"""The mandatory policy gate must be readable on every theme.

Every user passes through the safeguarding agreement before they can work,
and the document carries the escalation timeframes — "IMMEDIATE", "WITHIN 1
HOUR" — that matter most when someone needs them.

The agreement styles its accents from `--edify-accent` and `--edify-primary`,
both of which resolve to the brand blue #1872bd. The dark themes reuse that
value unchanged, so accent-coloured TEXT on the near-black agreement surface
measured 3.87:1 against a 4.5:1 AA floor — twelve failing strings on the page,
verified in a browser during the 2026-08 UI/UX audit. The dark themes now
lighten the accent for text; fills and borders keep the brand colour.

This test pins the override rather than the rendered ratio: measuring contrast
needs a browser, but a silent removal of these lines is what would bring the
failure back.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATE = (
    Path(settings.BASE_DIR)
    / "templates"
    / "pages"
    / "documents"
    / "canonical_document.html"
)


class AgreementAccentIsThemeAwareTest(SimpleTestCase):
    def test_dark_themes_override_the_agreement_accent_tokens(self):
        source = TEMPLATE.read_text(encoding="utf-8")

        self.assertIn(
            ":root.theme-dark",
            source,
            "the agreement no longer scopes anything to the dark theme; accent "
            "text on the dark surface falls back to the light-surface blue",
        )

        block = re.search(
            r":root\.theme-dark\s*,\s*:root\.theme-blue\s*\{(.*?)\}", source, re.S
        )
        self.assertIsNotNone(
            block, "the dark/blue theme override block for the agreement is gone"
        )
        body = block.group(1)
        for token in ("--agreement-blue", "--agreement-navy"):
            self.assertIn(
                token,
                body,
                f"{token} is not lightened for the dark themes, so text using it "
                "returns to 3.87:1 on the agreement's near-black surface",
            )

    def test_the_light_surface_brand_blue_is_not_reintroduced_for_dark_text(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        block = re.search(
            r":root\.theme-dark\s*,\s*:root\.theme-blue\s*\{(.*?)\}", source, re.S
        )
        self.assertNotIn(
            "#1872bd",
            block.group(1) if block else "",
            "the dark-theme override sets the very colour it exists to replace",
        )

    def test_the_accent_text_token_exists_and_lightens_on_dark_themes(self):
        """The value lives in the design system, not in the template.

        Templates may not carry raw hex (the platform's own UI-quality rule),
        and putting it in the design system makes the same AA-safe accent
        reusable for the other dark surfaces that still inherit the light
        theme's brand blue for text.
        """
        css = (
            Path(settings.BASE_DIR) / "static" / "css" / "design-system.css"
        ).read_text(encoding="utf-8")
        self.assertIn("--edify-accent-text", css)
        for scope in (":root.theme-dark", ":root.theme-blue"):
            index = css.index(scope)
            window = css[index : index + 400]
            self.assertIn(
                "--edify-accent-text",
                window,
                f"{scope} does not lighten the text accent, so accent text on "
                "its dark surfaces returns to 3.87:1",
            )
