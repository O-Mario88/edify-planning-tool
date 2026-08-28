"""Dark-theme warm tints must not inherit the constant dark warm-fill ink."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


CSS = Path(settings.BASE_DIR) / "static" / "css"
WARM = ("amber", "yellow", "orange", "lime")
REMAP = re.compile(r"\.dark\s+\.bg-(" + "|".join(WARM) + r")-(50|100)\b")


class WarmFillInkTest(SimpleTestCase):
    def test_every_dark_remapped_warm_tint_is_excluded_from_constant_ink(self):
        remapped = set()
        for sheet in CSS.rglob("*.css"):
            remapped.update(REMAP.findall(sheet.read_text(encoding="utf-8")))
        self.assertTrue(remapped, "warm-tint remap scanner matched nothing")

        consistency = (CSS / "consistency.css").read_text(encoding="utf-8")
        marker = "var(--edify-on-warm-fill) !important"
        end = consistency.index(marker)
        start = consistency.rfind("}", 0, end) + 1
        selector = consistency[start : consistency.rfind("{", start, end)]
        missing = [
            f"bg-{colour}-{step}"
            for colour, step in sorted(remapped)
            if f':not([class~="bg-{colour}-{step}"])' not in selector
        ]
        self.assertEqual(
            missing,
            [],
            "dark-remapped warm tints still receive constant dark ink",
        )
