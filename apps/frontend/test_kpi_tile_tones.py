"""Every tone a caller passes to a KPI tile has to have a gradient.

The tile's gradient is drawn from `--kpi-accent`, and the rule that draws it
matches ANY `kpi-strip__item--*` class. A tone with no accent mapping
therefore does not fall back to a neutral tile -- it falls through with the
variable unset and renders as a plain white card beside its coloured
siblings. `variant="finance"` did exactly that to Budget utilization on the
Accountant's home while the three tiles next to it were amber, red and green
(owner, 2026-09-04: "the tiles design is not applied system-wide").
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]

#: Builders that produce ONE tile. A tone/variant written near one of these
#: reaches `kpi-strip__item--<tone>` in the rendered strip.
ITEM_BUILDERS = (
    "render_metric(",
    "render_precomputed_metric_item(",
    "legacy_kpi_item",
    "kpi_item(",
)

#: Strip-level modifiers, not tile tones: they style `.kpi-strip--<name>`.
STRIP_MODIFIERS = {"executive", "supporting", "compact", "band", "inset"}

TONE_PATTERNS = (
    re.compile(r'variant="([a-z-]+)"'),
    re.compile(r'tone="([a-z-]+)"'),
    re.compile(r'"tone":\s*"([a-z-]+)"'),
    re.compile(r'"variant":\s*"([a-z-]+)"'),
)

#: How far after a builder call a tone still belongs to that call.
WINDOW = 600


def _sources():
    for base, suffix in ((ROOT / "apps", "*.py"), (ROOT / "templates", "*.html")):
        for path in base.rglob(suffix):
            if "/migrations/" in str(path) or path.name.startswith("test_"):
                continue
            yield path


def _tones_in_use() -> dict[str, str]:
    """tone -> the first file that asks for it, for a readable failure."""
    found: dict[str, str] = {}
    for path in _sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for builder in ITEM_BUILDERS:
            start = text.find(builder)
            while start != -1:
                window = text[start : start + WINDOW]
                for pattern in TONE_PATTERNS:
                    for tone in pattern.findall(window):
                        if tone in STRIP_MODIFIERS:
                            continue
                        found.setdefault(tone, str(path.relative_to(ROOT)))
                start = text.find(builder, start + 1)
    return found


class KpiTileToneContractTest(SimpleTestCase):
    def test_every_tone_in_use_has_an_accent(self):
        css = (ROOT / "static" / "css" / "components.css").read_text(encoding="utf-8")
        accented = set(
            re.findall(r"\.kpi-strip__item--([a-z-]+)\s*(?:,|\{)", css)
        )
        tones = _tones_in_use()
        self.assertTrue(tones, "the scan found no KPI tones — the builders moved")
        for tone, source in sorted(tones.items()):
            with self.subTest(tone=tone, source=source):
                self.assertIn(
                    tone,
                    accented,
                    f"{source} asks for tone '{tone}', which has no "
                    "--kpi-accent rule in components.css, so its tile renders "
                    "plain white beside its coloured siblings",
                )

    def test_a_four_tile_strip_never_wraps_three_plus_one(self):
        """Four tiles fit three columns but not four between 42rem and 56rem,
        so auto-fit dropped the fourth onto a row of its own."""
        css = (ROOT / "static" / "css" / "components.css").read_text(encoding="utf-8")
        self.assertIn(
            "@container kpi-strip (min-width: 42rem) and (max-width: 55.99rem)", css
        )
