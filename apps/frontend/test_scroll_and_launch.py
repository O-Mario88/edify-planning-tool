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
        self.assertIn('querySelectorAll(".app-sidebar__nav-container")', self.js)
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
        self.assertIn(
            'addEventListener("load", openWhenReady)'.replace('"', "'"), self.partial
        )
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
        self.band = self.css[
            self.css.index("The collapsed brand on a 10 or 11 inch tablet") :
        ]

    def test_the_rule_is_scoped_to_the_landscape_tablet_band(self):
        """That band, and only it: the desktop rail keeps the mark it has."""
        self.assertIn("@media (min-width: 64rem) and (max-width: 79.99rem)", self.band)
        self.assertIn(
            ".app-sidebar--collapsed .app-sidebar__brand-logo-compact", self.band
        )

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


class DashboardViewRailTest(SimpleTestCase):
    """Map | Operations: where the bar sits, and how soon it answers.

    The owner reported both together on 2026-09-07 — "very slow to respond,
    and the tabs are not professionally placed where they are supposed to be",
    on every role. Measured: a swap costs the server 300-700ms because the view
    rebuilds the whole dashboard whatever panel it is about to render, and the
    rail showed no sign of the press until that landed.
    """

    def setUp(self):
        self.markup = _read("templates/partials/dashboards/_view_tabs.html")
        self.css = _read("static/css/platform.css")

    def test_the_bar_spans_the_content_column(self):
        """It was shrunk to `max-content` to stop two tabs becoming two
        half-width slabs, which left a 306px control adrift at the left of a
        1120px column. Analytics solves both at once: a full-width bar whose
        tabs keep their own width."""
        band = self.css[self.css.index("The dashboard view rail (Map | Operations") :]
        band = band[: band.index("@media (max-width: 48rem)")]
        self.assertIn("inline-size: 100% !important;", band)
        self.assertNotIn("max-content", band)

    def test_the_tabs_do_not_stretch_to_fill_it(self):
        band = self.css[self.css.index("The dashboard view rail (Map | Operations") :]
        self.assertIn("flex: 0 0 auto !important;", band)
        self.assertIn("min-inline-size: 9.5rem !important;", band)

    def test_the_panel_is_not_welded_to_the_bar(self):
        """The gap belongs to the shell that holds both — every role's panel
        brings its own spacing, and one owner cannot double up."""
        self.assertIn("main [data-dashboard-view-shell]", self.css)

    def test_the_tab_answers_the_press_before_the_server_does(self):
        self.assertIn("other.classList.toggle('is-active', chosen)", self.markup)
        self.assertIn("data-server-active", self.markup)

    def test_a_failed_swap_puts_the_rail_back(self):
        self.assertIn("@htmx:response-error.window", self.markup)

    def test_the_last_press_wins(self):
        """Each tab is its own element, so htmx ran their requests
        independently: press one then the other and whichever response landed
        last decided what you were looking at."""
        self.assertIn('hx-sync="closest [data-dashboard-views]:replace"', self.markup)


class ViewPanelsHeldTest(SimpleTestCase):
    """A dashboard view, once loaded, stays loaded.

    A switch costs the server 300-700ms and 141 queries, and the same either
    way, because the view rebuilds the whole dashboard whichever panel it
    renders. The owner chose to keep each panel after its first load
    (2026-09-07); measured after: a return switch is 2-3ms and makes no request.
    """

    def setUp(self):
        self.js = _read("static/js/view-panels.js")

    def test_the_shell_loads_it_after_the_chart_system(self):
        base = _read("templates/base.html")
        self.assertIn("js/view-panels.js", base)
        self.assertLess(base.index("js/micro-ux.js"), base.index("js/view-panels.js"))

    def test_a_parked_panel_is_detached_not_hidden(self):
        """A panel left in the document with `display: none` still has a size
        of zero, and ApexCharts watches its own parent — a zero-size parent is
        what makes it write width="NaN" into its SVG."""
        self.assertIn("panel.remove();", self.js)
        self.assertIn("parked.set(view, panel);", self.js)

    def test_the_charts_are_torn_down_before_a_panel_leaves(self):
        """htmx is not involved in a switch between two panels already in hand,
        so the teardown that rides on `htmx:beforeSwap` never runs."""
        self.assertIn("window.EdifyChartSystem.destroyInside(panel)", self.js)

    def test_the_shell_not_the_rail_says_which_panel_is_held(self):
        """The pressed tab highlights before the request goes out, so between
        the press and the response the rail names the view being fetched.
        Parking by the rail files every panel under its successor's name."""
        self.assertIn("park(current);", self.js)
        self.assertNotIn("park(currentView());", self.js)

    def test_a_switch_that_skips_the_network_still_moves_the_address_bar(self):
        """Every tab is a real URL: a deep link, the back button and a press
        all land on the same page."""
        self.assertIn("window.history.pushState", self.js)
        self.assertIn('window.addEventListener("popstate"', self.js)

    def test_it_holds_nothing_across_a_reload(self):
        """A parked panel lives in memory, so a reload always re-reads the
        server and no one is served something older than their page."""
        self.assertNotIn("sessionStorage", self.js)
        self.assertNotIn("localStorage", self.js)


class TabsDoNotStretchTest(SimpleTestCase):
    """Tabs size to their labels; the rail keeps the rest as track."""

    def setUp(self):
        self.platform = _read("static/css/platform.css")
        self.interactions = _read("static/css/components/interactions.css")

    def test_tabs_stop_sharing_the_spare_rail_width(self):
        """`flex: 1 0 auto` drew two Batch Payments tabs at 530px and 588px and
        four /staff tabs between 231px and 309px."""
        block = self.platform[
            self.platform.index(
                "Tabs size to their labels; the rail keeps the rest as track"
            ) :
        ]
        self.assertIn("@media (min-width: 48rem)", block)
        self.assertIn("flex: 0 0 auto !important;", block)

    def test_a_phone_still_shares_the_rail(self):
        """There the tabs sharing the width is what makes them thumb-sized."""
        block = self.platform[
            self.platform.index(
                "Tabs size to their labels; the rail keeps the rest as track"
            ) :
        ]
        head = block[: block.index("@media (min-width: 48rem)")]
        self.assertIn("phone", head.lower())
        # The base contract, which phones fall back to, still grows its tabs.
        self.assertIn("flex: 1 0 auto !important;", self.platform)

    def test_every_rail_is_a_track_of_equal_chips(self):
        """With the tabs no longer filling the rail, rounding the first tab's
        outer corners and the last one's puts a rounded corner in the middle of
        the bar against a square edge — identical widths reading as different
        shapes."""
        block = self.interactions[
            self.interactions.index("A rail is a track of equal chips") :
        ]
        self.assertIn("@media (min-width: 48rem)", block)
        self.assertIn(
            "border-start-start-radius: calc(var(--edify-radius-sm) - 2px) !important;",
            block,
        )
        self.assertIn("padding: 3px !important;", block)
