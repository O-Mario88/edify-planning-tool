"""Country Oversight follows the plan live (owner, 2026-10-05).

"Every event should update (schedules, school withdrawal from the partner or
project, training schedules, ... activity completion etc) should update in
real time and fast."

The two lenses are the heaviest reads in the product, so they keep their
figures for a few minutes and rebuild them no more often than the settle
window allows (apps.planning.country_oversight.freshness). What is pinned
here is how that sits with a page that reads itself again on every change
(static/js/live-regions.js): which parts are read again, that a read inside
the settle window asks once more when newer figures are due, and that such a
read is never a forced rebuild of the whole country.
"""

from __future__ import annotations

import re
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone

from apps.planning.country_execution import service as esvc
from apps.planning.country_oversight import freshness
from apps.planning.country_oversight import service as svc
from apps.planning.test_country_planning_oversight import World


@override_settings(DASHBOARD_CACHE_SECONDS=300)
class WhenToAskAgain(SimpleTestCase):
    def setUp(self):
        cache.delete(freshness.CHANGED_KEY)
        self.addCleanup(cache.delete, freshness.CHANGED_KEY)

    def test_figures_the_plan_has_not_overtaken_are_not_asked_for_again(self):
        built = timezone.now()

        self.assertEqual(freshness.settles_in(built), 0)
        freshness.note_change()
        self.assertEqual(freshness.settles_in(timezone.now()), 0)

    def test_inside_the_settle_window_it_waits_the_window_out(self):
        built = timezone.now() - timedelta(seconds=5)
        freshness.note_change()

        wait = freshness.settles_in(built)

        self.assertGreater(wait, freshness.SETTLE_SECONDS - 7)
        self.assertLessEqual(wait, freshness.SETTLE_SECONDS)

    def test_a_rebuild_already_due_is_asked_for_after_a_pause_not_at_once(self):
        """Another reader holds the rebuild: asking again every second would
        be a page reading itself without rest."""
        built = timezone.now() - timedelta(seconds=90)
        freshness.note_change()

        self.assertEqual(freshness.settles_in(built), freshness.RECHECK_FLOOR_SECONDS)

    @override_settings(DASHBOARD_CACHE_SECONDS=0)
    def test_figures_built_on_every_read_never_ask(self):
        freshness.note_change()

        self.assertEqual(freshness.settles_in(timezone.now() - timedelta(seconds=5)), 0)

    def test_the_page_reading_itself_names_itself(self):
        factory = RequestFactory()

        self.assertTrue(
            freshness.live_read(factory.get("/", HTTP_X_REQUESTED_WITH="EdifyLive"))
        )
        self.assertFalse(freshness.live_read(factory.get("/")))
        self.assertFalse(
            freshness.live_read(
                factory.get("/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            )
        )


class TheLensesAreReadAgain(World):
    PLANNING = ("cpo-stamp", "cpo-summary", "cpo-types", "cpo-charts", "cpo-drill")
    EXECUTION = (
        "cxo-summary",
        "cxo-charts",
        "cxo-readings",
        "cxo-types",
        "cxo-issues",
        "cxo-recent",
    )

    def setUp(self):
        super().setUp()
        self.school("core", self.cceo)
        self.browser = self.as_user(self.cd_user)

    def _marked(self, body: str) -> set[str]:
        """The ids of the elements that carry the live mark."""
        return {
            match.group(1)
            for match in re.finditer(r'<[a-z]+\b[^>]*\bid="([^"]+)"[^>]*>', body)
            if re.search(r"\sdata-live-region[\s>]", match.group(0))
        }

    def test_the_planning_lens_marks_its_figures(self):
        body = self.browser.get("/country-planning-oversight/").content.decode()

        self.assertEqual(self._marked(body), set(self.PLANNING))

    def test_a_reader_with_rows_open_is_left_alone(self):
        """The drill-down gives up its mark while a Lead is open or the
        country is folded, and reads itself once they are closed."""
        body = self.browser.get("/country-planning-oversight/").content.decode()

        self.assertIn(
            """:data-live-region="openLeads || !country ? false : ''\"""", body
        )
        self.assertIn("this.openLeads += this.open ? 1 : -1", body)
        self.assertIn("window.EdifyLive.refresh()", body)

    def test_the_tab_a_reader_chose_survives_the_redraw(self):
        body = self.browser.get("/country-planning-oversight/").content.decode()

        self.assertIn("view: window.cpoTypesView || 'schools'", body)
        self.assertIn("view: window.cpoDrillView || 'workload'", body)

    def test_the_execution_lens_marks_all_but_its_table(self):
        body = self.browser.get(
            "/country-planning-oversight/", {"view": "execution"}
        ).content.decode()

        self.assertEqual(self._marked(body), set(self.EXECUTION))
        # Which of its five tables is showing is not in the address.
        self.assertIn('id="cxo-table"', body)

    def test_figures_behind_the_plan_ask_once_more(self):
        with mock.patch.object(freshness, "settles_in", return_value=7):
            behind = self.browser.get("/country-planning-oversight/").content.decode()
        current = self.browser.get("/country-planning-oversight/").content.decode()

        self.assertIn("window.EdifyLive.refresh(), 7000)", behind)
        self.assertNotIn("cpoSettle", current)

    def test_the_execution_lens_asks_once_more_too(self):
        with mock.patch.object(freshness, "settles_in", return_value=9):
            behind = self.browser.get(
                "/country-planning-oversight/", {"view": "execution"}
            ).content.decode()

        self.assertIn("window.EdifyLive.refresh(), 9000)", behind)

    def test_a_live_read_never_forces_a_rebuild(self):
        """A reader who pressed "read again" keeps refresh=1 in the address;
        every change in the country would otherwise rebuild the whole fold."""
        with mock.patch.object(svc, "snapshot_for", wraps=svc.snapshot_for) as fold:
            self.browser.get(
                "/country-planning-oversight/",
                {"refresh": "1"},
                HTTP_X_REQUESTED_WITH="EdifyLive",
            )
            self.assertFalse(fold.call_args.kwargs["refresh"])
            self.browser.get("/country-planning-oversight/", {"refresh": "1"})
            self.assertTrue(fold.call_args.kwargs["refresh"])

    def test_nor_on_the_execution_lens(self):
        with mock.patch.object(esvc, "snapshot_for", wraps=esvc.snapshot_for) as fold:
            self.browser.get(
                "/country-planning-oversight/",
                {"view": "execution", "refresh": "1"},
                HTTP_X_REQUESTED_WITH="EdifyLive",
            )
            self.assertFalse(fold.call_args.kwargs["refresh"])
