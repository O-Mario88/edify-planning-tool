"""Page scripts must not make the browser restyle the whole page for nothing.

On a long page every full style resolution is expensive: a realistic officer's
My Plan (6,300 elements) took ~0.8 s per resolution and ~1 s per layout on an
unthrottled browser. The 2026-09-24 audit traced about 9 s of forced style
and layout work on that page during load. Most of it came from scripts that
wrote to the document and then read a style or a size back, each read
forcing the browser to redo the page:

- the theme component re-applied, unchanged, the theme the head script had
  already set, then read a computed style (~0.9 s, also on every tab return);
- the head script added `theme-fade` to <html> after every load: one more
  full restyle, and colour transitions left on every table cell;
- the scroll memory picked the visible sidebar by reading layout at
  DOMContentLoaded (~1 s);
- the web-font check read `document.fonts.status`, which resolves style
  first (~0.7 s before first paint);
- the tab rails and the table scroll regions measured one at a time, writing
  between measurements, forcing a layout per rail and per table.

After the fixes the same trace measured ~4.8 s instead of ~9.3 s. These tests
pin the fixes in the source, the way the page's other behaviour is pinned.
"""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


class ForcedStyleResolutionTest(SimpleTestCase):
    def test_the_head_script_leaves_theme_fade_off_on_load(self):
        head = _read("templates/base.html")
        self.assertNotIn("classList.add('theme-fade')", head)

    def test_an_unchanged_theme_is_not_reapplied(self):
        js = _read("static/js/alpine-components.js")
        start = js.index("applyTheme(mode, persist = true)")
        body = js[start : js.index("setTheme(mode)", start)]
        unchanged = body.index("html.dataset.theme === actual")
        self.assertLess(
            unchanged,
            body.index("getComputedStyle"),
            "the unchanged-theme return must come before the computed-style read",
        )
        # The fade is applied only across a real switch, and taken off again.
        self.assertIn("html.classList.add('theme-fade')", body)
        self.assertIn("html.classList.remove('theme-fade')", body)

    def test_the_font_check_does_not_force_style(self):
        js = _read("static/js/micro-ux.js")
        self.assertNotIn("document.fonts.status", js)
        self.assertIn("document.fonts.ready.then", js)

    def test_the_scroll_memory_does_not_read_layout_to_listen(self):
        js = _read("static/js/scroll-memory.js")
        watch = js[js.index("function watch()") : js.index("function start()")]
        self.assertNotIn("sidebar()", watch)
        self.assertNotIn("clientHeight", watch)

    def test_rails_and_scroll_regions_measure_before_they_write(self):
        js = _read("static/js/micro-ux.js")
        rails = js[js.index("function fitRails(root)") :]
        rails = rails[: rails.index("\n  }\n") + 4]
        # Every rail measured before any toggle is shown, and every toggle
        # shown before any rail is planned.
        self.assertLess(rails.index("overflowing"), rails.index("more.hidden = false"))
        self.assertLess(rails.index("more.hidden = false"), rails.index("planRail("))
        regions = js[js.index("function watchScrollRegions(root)") :]
        regions = regions[: regions.index("\n  }\n") + 4]
        self.assertLess(
            regions.index("scrollStateOf"), regions.index("applyScrollState")
        )
