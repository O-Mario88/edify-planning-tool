"""Regressions for empty-state glyphs, complete priority lists and offline updates."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.utils.html import strip_tags

from apps.frontend.views.pwa_views import static_version


class PageAnomalyTest(SimpleTestCase):
    def test_empty_state_path_is_an_svg_attribute_not_visible_text(self):
        path = "M19 11H5m14 0a2 2 0 012 2"
        html = render_to_string(
            "components/empty_state.html",
            {"title": "Empty queue", "message": "Nothing here", "icon_path": path},
        )
        self.assertIn(f'd="{path}"', html)
        self.assertNotIn(path, strip_tags(html))
        self.assertEqual(html.count("<svg"), 1)

    def test_priority_count_does_not_hide_the_ninth_action(self):
        rows = [
            {"title": f"Priority {n}", "url": f"/planning?item={n}", "action": "Plan"}
            for n in range(9)
        ]
        html = render_to_string(
            "partials/targets/priority_portfolio.html",
            {"priority_groups": [{"key": "ssa", "label": "SSA", "rows": rows}]},
        )
        self.assertEqual(html.count('href="/planning?item='), 9)
        self.assertIn("Priority 8", html)

    def test_offline_cache_changes_with_templates_even_without_a_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [
                "templates/base.html",
                "templates/pages/offline.html",
                "static/js/field-outbox.js",
            ]
            for name in sources:
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(name)
            with (
                override_settings(BASE_DIR=root, STATIC_ROOT=root / "collected"),
                patch.dict(os.environ, {"STATIC_VERSION": "", "RELEASE_SHA": ""}),
            ):
                before = static_version()
                self.assertEqual(before, static_version())
                for name in sources:
                    (root / name).write_text(name + " updated")
                    after = static_version()
                    self.assertNotEqual(before, after)
                    before = after

    def test_offline_queue_code_is_available_without_an_external_request(self):
        response = self.client.get("/offline")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<script data-offline-outbox>")
        self.assertContains(response, "window.EdifyFieldOutbox = Object.freeze")
