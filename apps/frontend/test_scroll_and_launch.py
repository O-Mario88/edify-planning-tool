"""Keeping the reader's place, and what the launch screen is for.

Two owner reports on 2026-09-07.

THE PAGE RESETTING TO THE TOP — on a tab, on pagination, on a refresh, and the
sidebar doing the same on every menu click. One cause: this shell does not
scroll the document. The top bar and sidebar are pinned and the workspace has
its own scrollbar, so `#main-content` is the scroller and `window.scrollY`
never leaves zero — exactly the case a browser cannot restore for you. Measured
before the fix: the workspace sat at 781px, and 0 after a refresh.

THE LAUNCH SCREEN. The first reading of this was wrong and the logo was taken
off the screen; the owner meant the opposite. The launch screen keeps the
sidebar's wordmark. What they did not want was the ROUND APP ICON that shows
before it — and that screen is not ours: Android and desktop Chrome generate it
from the installed manifest, icon centred on `background_color`, and no markup
in this repo can remove it. The app's only move is to share that colour so the
two read as one field, which it does.
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

    def test_it_carries_the_same_wordmark_the_sidebar_does(self):
        """The owner asked for the sidebar's logo here (2026-09-07). The round
        icon that opens a launch is a different thing entirely — Android and
        desktop Chrome generate that screen from the manifest, and no markup
        here can remove it."""
        sidebar = _read("templates/components/sidebar.html")
        self.assertIn("images/logo.png", sidebar)
        self.assertIn("images/logo.png", self.partial)
        self.assertIn("edify-launch__wordmark", self.partial)

    def test_the_ground_does_not_change_when_the_os_screen_hands_over(self):
        """The one thing the app CAN do about that first screen: share its
        colour, so the icon lifts and the lockup arrives on the same field."""
        pwa = _read("apps/frontend/views/pwa_views.py")
        self.assertIn('BRAND = "#2d4862"', pwa)
        self.assertIn('"background_color": BRAND', pwa)
        self.assertIn("background: #2d4862;", self.partial)

    def test_it_shows_the_waiting_state_as_well_as_the_lockup(self):
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


class CollapsedRailBrandTest(SimpleTestCase):
    """The sidebar's mark on a 10 or 11 inch tablet.

    The landscape tablet band is the one width where the sidebar collapses on
    its own — layouts/shell.html opens it as a rail between 64rem and 80rem —
    so this mark is what a tablet user sees on every screen rather than
    something they chose. At the desktop size it is the wordmark cropped to a
    36px square, which on a 72px rail reads as "ec": a partial word, and taller
    than the icons beneath it. The owner asked for it smaller and fitted
    (2026-09-07).
    """

    def setUp(self):
        self.css = _read("static/css/components/sidebar.css")
        self.band = self.css[self.css.index("The collapsed brand on a 10 or 11 inch tablet") :]

    def test_the_rule_is_scoped_to_the_landscape_tablet_band(self):
        """That band, and only it: the desktop rail keeps the mark it has."""
        self.assertIn("@media (min-width: 64rem) and (max-width: 79.99rem)", self.band)
        self.assertIn(".app-sidebar--collapsed .app-sidebar__brand-logo-compact", self.band)

    def test_the_mark_is_whole_rather_than_cropped(self):
        self.assertIn("overflow: visible;", self.band)
        self.assertIn("object-fit: contain;", self.band)

    def test_it_is_sized_to_the_rail(self):
        self.assertIn("width: 100%;", self.band)
        self.assertIn("height: auto;", self.band)

    def test_the_band_is_the_one_the_shell_collapses_at(self):
        """If the shell's auto-collapse band moves, this rule has to move with
        it or a tablet gets the desktop crop back."""
        shell = _read("templates/layouts/shell.html")
        self.assertIn("(min-width: 64rem) and (max-width: 79.99rem)", shell)
