"""Workflow links written in code resolve to a real page.

Handoffs between workflows travel as links: a planning risk's "Verify the
submission", a KPI tile's drill-down, a notification's action, a redirect after
a decision. The 2026-09-13 ecosystem audit found six of them pointing at routes
that never existed (/ia/verification-queue, /finance/accountability,
/budget/amendments, /planning/my-actions, /system-health/jobs/<job>, and
/hr/performance), each a 404 at the moment someone was asked to act.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import Resolver404, resolve

LINK_CONTEXT = re.compile(
    r"""(?:\b(?:route|drilldown|target_route|workflow_route|href|url|link|next_url|success_url)\s*=\s*|redirect\(\s*|["'](?:route|drilldown|href|url|link|targetRoute|target_route)["']\s*:\s*)f?["'](/[^"'\s]*)["']"""
)


def _resolves(path: str) -> bool:
    for candidate in {path, path.rstrip("/") or "/", path.rstrip("/") + "/"}:
        try:
            resolve(candidate)
            return True
        except Resolver404:
            continue
    return False


class WorkflowLinkLiteralsTest(SimpleTestCase):
    def test_every_link_literal_in_the_apps_resolves(self):
        root = Path(settings.BASE_DIR) / "apps"
        broken = []
        scanned = 0
        for source in root.rglob("*.py"):
            name = str(source)
            if "/migrations/" in name or "/test" in name or name.endswith("tests.py"):
                continue
            text = source.read_text(encoding="utf-8", errors="ignore")
            for match in LINK_CONTEXT.finditer(text):
                raw = match.group(1)
                if raw.startswith(("/static/", "/media/", "/api/")) or "//" in raw:
                    continue  # assets, APIs, and open-redirect examples in docstrings
                brace = raw.find("{")
                if brace != -1 and raw[brace - 1] != "/":
                    # A placeholder glued to a segment is a query string or a
                    # suffix; the route is the part before it.
                    raw = raw[:brace]
                elif brace != -1 and "}" not in raw[brace:]:
                    # The f-string's own quotes ended the match mid-placeholder
                    # (f"/help/articles/{row['slug']}"): it is still one segment.
                    raw = raw[:brace] + "x1"
                path = urlsplit(re.sub(r"\{[^}]*\}", "x1", raw)).path
                if not path or path == "/":
                    continue
                scanned += 1
                if not _resolves(path):
                    line = text[: match.start()].count("\n") + 1
                    broken.append(f"{source.relative_to(root.parent)}:{line} {raw}")
        self.assertGreater(
            scanned, 300, "the link scan found too little to be meaningful"
        )
        self.assertEqual(broken, [])
