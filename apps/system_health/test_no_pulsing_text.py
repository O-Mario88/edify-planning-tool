"""Accessibility invariant: readable text never animates its opacity."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


PULSING = re.compile(
    r"<(?P<tag>span|div|p|a|button|li|strong|em|h[1-6])\b[^>]*"
    r"\banimate-pulse\b[^>]*>(?P<body>.*?)</(?P=tag)>",
    re.S,
)
MARKUP = re.compile(r"<[^>]+>")


class NoPulsingTextTest(SimpleTestCase):
    def test_no_text_sits_inside_a_pulse_animation(self):
        offenders = []
        matched = 0
        for path in sorted((Path(settings.BASE_DIR) / "templates").rglob("*.html")):
            source = path.read_text(encoding="utf-8")
            for match in PULSING.finditer(source):
                matched += 1
                body = MARKUP.sub("", match.group("body")).strip()
                if body:
                    line = source[: match.start()].count("\n") + 1
                    offenders.append(
                        f"{path.relative_to(settings.BASE_DIR)}:{line} -> {body[:60]!r}"
                    )
        self.assertGreaterEqual(
            matched, 10, "pulse scanner no longer sees its controls"
        )
        self.assertEqual(
            offenders,
            [],
            "text inside animate-pulse loses contrast during every opacity cycle:\n  "
            + "\n  ".join(offenders),
        )
