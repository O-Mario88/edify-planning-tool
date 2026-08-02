"""The card scan must find real duplicates and stay quiet about false ones.

Every assertion here exists because an earlier version of the scan got it
wrong. In order: it counted one card three times because nested wrappers each
claimed the same heading; it read ``<h3>{{ a }} / {{ b }}</h3>`` as a card
titled "/"; and when that was fixed with a crude "is there an {% else %}
between them" test, it stopped seeing the genuinely duplicated card on the
Admin dashboard. A scan that misses a real defect is worse than one that
reports a false one, so both directions are pinned.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.test import SimpleTestCase

from apps.system_health.card_inventory import (
    _CHROME_RE,
    _NOT_A_CARD,
    CardSite,
    _branch_paths_by_line,
    _clean,
    build_inventory,
)


def _site(line, title, branch_path=()):
    return CardSite(
        template="t.html",
        line=line,
        title=title,
        heading_level=3,
        has_card_key=False,
        classes="",
        branch_path=branch_path,
    )


class HeadingCleaningTests(SimpleTestCase):
    def test_a_plain_title_survives(self):
        self.assertEqual(
            _clean("Schools Needing Urgent Attention"),
            "Schools Needing Urgent Attention",
        )

    def test_markup_is_stripped(self):
        self.assertEqual(
            _clean('<span class="x">Budget</span> Snapshot'), "Budget Snapshot"
        )

    def test_a_value_heading_is_not_a_title(self):
        """`<h3>{{ period.achieved }} / {{ period.target }}</h3>` is a figure."""
        self.assertEqual(_clean("{{ period.achieved }} / {{ period.target }}"), "")

    def test_a_heading_of_only_punctuation_is_not_a_title(self):
        self.assertEqual(_clean(" — · "), "")

    def test_a_title_with_a_number_still_counts(self):
        self.assertEqual(_clean("Top 5 Schools"), "Top 5 Schools")


class BranchPathTests(SimpleTestCase):
    def test_lines_outside_a_conditional_have_no_branch(self):
        paths = _branch_paths_by_line("<div>a</div>\n<div>b</div>\n")
        self.assertEqual(paths[1], ())

    def test_the_two_arms_of_one_conditional_differ(self):
        source = "{% if x %}\nA\n{% else %}\nB\n{% endif %}\n"
        paths = _branch_paths_by_line(source)
        self.assertNotEqual(paths[2], paths[4])

    def test_both_arms_name_the_same_block(self):
        source = "{% if x %}\nA\n{% else %}\nB\n{% endif %}\n"
        paths = _branch_paths_by_line(source)
        self.assertEqual({b for b, _ in paths[2]}, {b for b, _ in paths[4]})

    def test_an_unrelated_conditional_does_not_link_two_lines(self):
        source = "A\n{% if x %}\nB\n{% else %}\nC\n{% endif %}\nD\n"
        paths = _branch_paths_by_line(source)
        self.assertEqual(paths[1], ())
        self.assertEqual(paths[7], ())


class DuplicateDetectionTests(SimpleTestCase):
    """`_renders_together` is what separates a duplicate from an empty state."""

    def _inventory(self, cards):
        from apps.system_health.card_inventory import CardInventory

        inv = CardInventory()
        inv.cards = cards
        return inv

    def test_two_cards_outside_any_conditional_are_a_duplicate(self):
        inv = self._inventory(
            [_site(10, "Team Target Progress"), _site(90, "Team Target Progress")]
        )
        self.assertIn("t.html", inv.duplicate_titles_within_a_template())

    def test_a_card_and_its_empty_state_are_not_a_duplicate(self):
        inv = self._inventory(
            [
                _site(10, "Workflow Context", branch_path=((1, 0),)),
                _site(90, "Workflow Context", branch_path=((1, 1),)),
            ]
        )
        self.assertEqual(inv.duplicate_titles_within_a_template(), {})

    def test_an_unrelated_conditional_does_not_excuse_a_duplicate(self):
        """The bug that made the scan miss the Admin dashboard."""
        inv = self._inventory(
            [
                _site(10, "Team Target Progress", branch_path=((1, 0),)),
                _site(90, "Team Target Progress", branch_path=((7, 0),)),
            ]
        )
        self.assertIn("t.html", inv.duplicate_titles_within_a_template())

    def test_distinct_titles_are_never_reported(self):
        inv = self._inventory(
            [_site(10, "Priority Schools"), _site(90, "Cluster Performance")]
        )
        self.assertEqual(inv.duplicate_titles_within_a_template(), {})


class UntitledSurfaceClassificationTests(SimpleTestCase):
    """The scan skips ~1,000 surfaces; it must say why, not just how many.

    Reported as one number, "1,000 untitled surfaces" reads as a thousand
    unaudited cards. Split by cause it reads as what it is: decoration, regions
    inside cards the parent heading already titles, and non-card surfaces
    (filters, flash alerts, empty states, KPI tiles, action footers).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inventory = build_inventory()

    def test_the_untitled_total_is_fully_accounted_for(self):
        summary = self.inventory.summary()
        self.assertEqual(
            summary["untitled_surfaces"],
            summary["untitled_chrome"]
            + summary["untitled_nested"]
            + summary["untitled_headless"],
        )

    def test_icon_wrappers_are_classified_as_chrome(self):
        """`w-12 h-12 rounded-surface` is a 3rem icon disc, not a card.

        An earlier `\\bw-\\d\\b` could not match inside `w-12` -- the trailing
        word boundary falls between two digits -- so every icon wrapper on the
        platform counted as an untitled card.
        """
        self.assertTrue(_CHROME_RE.search("w-12 h-12 rounded-surface bg-slate-50"))
        self.assertTrue(_CHROME_RE.search("h-11 w-11 rounded-surface"))

    def test_a_plain_card_surface_is_not_chrome(self):
        self.assertFalse(
            _CHROME_RE.search("edify-surface rounded-surface border shadow-sm p-5")
        )

    def test_kpi_families_are_not_counted_as_cards(self):
        """KPI tiles are inventoried by `kpi_inventory`, not here."""
        for cls in ("partner-kpi-card", "admin-kpi", "kpi-strip__item"):
            with self.subTest(cls):
                self.assertTrue(_NOT_A_CARD.search(cls))

    def test_chrome_is_a_meaningful_share_of_the_untitled_surfaces(self):
        self.assertGreater(self.inventory.untitled_chrome, 100)


class LiveTemplateScanTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inventory = build_inventory()

    def test_the_scan_finds_the_card_surface(self):
        self.assertGreater(len(self.inventory.cards), 300)

    def test_checked_in_manifest_matches_the_live_templates(self):
        from pathlib import Path

        path = Path(settings.BASE_DIR) / "docs/platform-card-inventory.json"
        checked_in = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            checked_in,
            json.loads(json.dumps(self.inventory.as_dict())),
            "platform-card-inventory.json is stale; run build_card_inventory",
        )

    def test_no_page_renders_the_same_card_title_twice(self):
        """§6 of the card mandate: required same-page duplicate count is 0."""
        duplicates = self.inventory.duplicate_titles_within_a_template()
        self.assertEqual(
            duplicates,
            {},
            "two cards on one page claim the same thing; merge or rename them",
        )

    def test_every_card_records_where_it_was_found(self):
        for card in self.inventory.cards:
            with self.subTest(f"{card.template}:{card.line}"):
                self.assertTrue(card.template.endswith(".html"))
                self.assertGreater(card.line, 0)
                self.assertTrue(card.title.strip())

    def test_the_messages_panel_empty_state_is_not_flagged(self):
        """A card and its `{% else %}` empty state share a title by design."""
        panel = [
            c
            for c in self.inventory.cards
            if c.template.endswith("messages/context_panel.html")
            and c.title_key == "workflow context"
        ]
        self.assertEqual(len(panel), 2, "expected the card and its empty state")
        self.assertNotIn(
            "templates/partials/messages/context_panel.html",
            self.inventory.duplicate_titles_within_a_template(),
        )
