"""One type standard for the whole platform.

Owner, 2026-10-10: "change the typography of the entire platform to look like
the attached reference ... everything should have the consistent size and
font weight across the platform. Look at the staff activity page table
typography and use it as a gold standard."

That table reads in three weights — cells medium (500), the name that opens
the record semibold (600), column names bold (700) — and its cells are the
13.7px step every paragraph and field value now shares. Before, six weights
were in use (400, 450, 500, 550, 600, 700) and body copy was a step larger
and lighter than a cell, so the same kind of line read differently from one
page to the next.

Held here, at the source, so a stylesheet cannot bring a fourth weight back:
the tokens say the standard, and no rule writes a weight outside it.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

CSS = Path(settings.BASE_DIR) / "static" / "css"
#: Generated or third-party: Tailwind's bundles carry its own utility values
#: (the shell maps those utilities onto the three weights), and the build
#: folder is a copy of the sources checked here.
SKIPPED = {"main.css", "tokens.css"}
STANDARD_WEIGHTS = {"500", "600", "700"}
#: Not a weight of text: `normal`/`inherit` hand the choice back, and 0–300
#: do not occur. Anything numeric must be one of the three.
_WEIGHT = re.compile(r"font-weight:\s*(\d{3})\b")
_TOKEN = re.compile(r"(--edify-(?:text|table)-[a-z-]+):\s*([^;]+);")


def _sources():
    for path in sorted(CSS.rglob("*.css")):
        relative = path.relative_to(CSS)
        if relative.parts[0] in {"vendor", "build"} or path.name in SKIPPED:
            continue
        yield relative, path.read_text(encoding="utf-8")


def _tokens() -> dict[str, str]:
    text = (CSS / "design-system.css").read_text(encoding="utf-8")
    root = text[: text.index("@media (orientation: landscape)")]
    return {name: value.strip() for name, value in _TOKEN.findall(root)}


class TypeStandardTest(SimpleTestCase):
    def test_text_is_one_of_three_weights(self):
        tokens = _tokens()

        self.assertEqual(tokens["--edify-text-body-weight"], "500")
        self.assertEqual(tokens["--edify-text-micro-weight"], "500")
        self.assertEqual(tokens["--edify-table-body-weight"], "500")
        self.assertEqual(tokens["--edify-text-label-weight"], "600")
        self.assertEqual(tokens["--edify-table-identity-weight"], "600")
        for name in ("title", "heading", "display"):
            self.assertEqual(tokens[f"--edify-text-{name}-weight"], "700")
        self.assertEqual(tokens["--edify-table-header-weight"], "700")

    def test_a_paragraph_and_a_cell_are_one_size(self):
        tokens = _tokens()

        self.assertEqual(
            tokens["--edify-text-body-size"], "var(--edify-text-label-size)"
        )
        self.assertEqual(
            tokens["--edify-text-table-size"], "var(--edify-text-label-size)"
        )
        # Column names are the one step above the cells, a table's name and
        # every other section title the step above that.
        self.assertEqual(
            tokens["--edify-text-table-heading-size"], "var(--edify-text-lead-size)"
        )
        self.assertEqual(
            tokens["--edify-text-heading-size"], "var(--edify-text-title-size)"
        )
        self.assertEqual(
            tokens["--edify-text-table-title-size"], "var(--edify-text-title-size)"
        )

    def test_no_stylesheet_writes_a_fourth_weight(self):
        strays = []
        for relative, text in _sources():
            for match in _WEIGHT.finditer(text):
                if match.group(1) not in STANDARD_WEIGHTS:
                    line = text.count("\n", 0, match.start()) + 1
                    strays.append(f"{relative}:{line} font-weight {match.group(1)}")

        self.assertEqual(
            strays,
            [],
            "text is medium (500), semibold (600) or bold (700): "
            "use a weight token, or one of the three",
        )
