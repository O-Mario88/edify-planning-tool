"""Every standalone document must declare viewport-fit=cover.

The safe-area rules across the platform — the shell insets in
components/mobile-shell.css, the IA review workspace's mobile decision bar,
and login.css's own top/bottom padding — all resolve to 0 on iOS unless the
viewport meta opts in. There is no visual failure when it is missing: the
padding silently becomes nothing, which is why this is worth pinning.

base.html and layouts/login.html are separate root documents. login.html does
not extend base.html, so it did not inherit the attribute when base.html gained
it, and sign-in — the first screen a field user sees — kept rendering under the
notch. This test is the guard against that pairing drifting apart again.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

TEMPLATES = Path(__file__).resolve().parents[3] / "templates"
VIEWPORT = re.compile(r'<meta\s+name="viewport"\s+content="([^"]*)"')


def root_documents() -> list[Path]:
    """Templates that own a <head> rather than extending one."""
    return sorted(
        p
        for p in TEMPLATES.rglob("*.html")
        if re.search(r"<!doctype html>", p.read_text(errors="replace"), re.I)
    )


class ViewportMetaTests(SimpleTestCase):
    def test_there_are_root_documents_to_check(self):
        # Guards the discovery itself: a glob that silently matches nothing
        # would make every assertion below vacuously true.
        self.assertGreaterEqual(len(root_documents()), 2)

    def test_every_root_document_declares_viewport_fit_cover(self):
        for path in root_documents():
            rel = path.relative_to(TEMPLATES)
            with self.subTest(template=str(rel)):
                found = VIEWPORT.search(path.read_text(errors="replace"))
                self.assertIsNotNone(found, f"{rel} has no viewport meta")
                self.assertIn(
                    "viewport-fit=cover",
                    found.group(1),
                    f"{rel} omits viewport-fit=cover, so every "
                    "env(safe-area-inset-*) it renders resolves to 0 on iOS",
                )

    def test_safe_area_css_has_a_document_that_enables_it(self):
        # The rules exist; this asserts they are not inert.
        css = (
            TEMPLATES.parents[0] / "static" / "css" / "components" / "mobile-shell.css"
        )
        self.assertIn("env(safe-area-inset-bottom", css.read_text())
