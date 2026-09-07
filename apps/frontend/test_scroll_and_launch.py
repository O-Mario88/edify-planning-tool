"""Keeping the reader's place, and a launch screen that is only the wait.

Two owner reports on 2026-09-07:

  * "When you click a tab or pagination, or refreshed the page, the page resets
    to the top… the sidebar also has the same behaviour."
  * "On the loading page, remove the app icon logo and start the app loading
    page direct, not opening the logo then the loading page. The logo should
    just be for installing on the computer or the app and on the url."

The first has one cause: this shell does not scroll the document. The top bar
and sidebar are pinned and the workspace has its own scrollbar, so
`#main-content` is the scroller and `window.scrollY` never leaves zero — which
is exactly the case a browser cannot restore for you. Measured before the fix:
the workspace sat at 781px, and 0 after a refresh.
"""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


class ScrollMemoryTest(SimpleTestCase):
    def setUp(self):
        self.js = _read("static/js/scroll-memory.js")

    def test_the_shell_loads_it(self):
        base = _read("templates/base.html")
        self.assertIn("js/scroll-memory.js", base)

    def test_it_remembers_the_workspace_and_the_sidebar(self):
        self.assertIn('document.getElementById("main-content")', self.js)
        self.assertIn(".app-sidebar__nav-container", self.js)

    def test_it_takes_the_sidebar_that_is_actually_on_screen(self):
        """Two elements carry that class — the mobile sidebar's, which is in
        the markup on every page at zero height, and the desktop one.
        `querySelector` returns the mobile one, which never scrolls."""
        self.assertIn("querySelectorAll(\".app-sidebar__nav-container\")", self.js)
        self.assertIn("clientHeight > 0", self.js)

    def test_the_workspace_is_keyed_by_path_not_by_query(self):
        """Page two of a table, and the same table under another filter, are
        both somewhere the reader arrives from where they already were."""
        self.assertIn("PREFIX + window.location.pathname", self.js)

    def test_the_sidebar_is_one_position_for_the_session(self):
        """It is the same menu on every screen."""
        self.assertIn('SIDEBAR_KEY = PREFIX + "sidebar"', self.js)

    def test_it_forgets_after_a_while(self):
        self.assertIn("MAX_AGE_MS", self.js)

    def test_it_stops_the_moment_the_reader_scrolls(self):
        """Restoring runs across a few frames while late content lands, so it
        has to yield rather than fight a deliberate scroll."""
        self.assertIn("surrendered", self.js)
        self.assertIn('addEventListener("wheel", giveUp', self.js)

    def test_a_storage_failure_cannot_break_the_page(self):
        """Private windows throw on sessionStorage access, not on use."""
        self.assertIn("function store()", self.js)
        self.assertIn("return null;", self.js)


class LaunchScreenTest(SimpleTestCase):
    def setUp(self):
        self.partial = _read("templates/partials/pwa_launch.html")

    def test_the_launch_screen_carries_no_logo(self):
        """The mark identifies the app when it is NOT running. Showing it again
        on the way in made launching a two-part ceremony."""
        self.assertNotIn("<img", self.partial)
        self.assertNotIn("images/logo.png", self.partial)
        self.assertNotIn("edify-launch__wordmark {", self.partial)
        self.assertNotIn("edify-launch__lockup {", self.partial)

    def test_it_is_the_waiting_state_and_nothing_else(self):
        self.assertIn("Loading your workspace", self.partial)
        self.assertIn("Preparing your dashboard", self.partial)

    def test_it_leaves_when_the_app_is_ready_not_after_a_set_time(self):
        self.assertIn("function openWhenReady()", self.partial)
        self.assertIn('addEventListener("load", openWhenReady)'.replace('"', "'"), self.partial)
        self.assertNotIn("var HOLD =", self.partial)

    def test_it_still_cannot_strand_the_reader(self):
        """If `load` never fires or a timer is throttled, it comes down anyway."""
        self.assertIn("CEILING", self.partial)
        self.assertIn("window.setTimeout(open, CEILING);", self.partial)

    def test_the_mark_still_identifies_the_app_where_it_should(self):
        head = _read("templates/partials/pwa_head.html")
        self.assertIn('rel="manifest"', head)
        self.assertIn("apple-touch-icon", head)
        self.assertIn('rel="icon"', head)
