"""The Admin dashboard's cards are read as lists drawn as those cards.

Critical Now, Recent Incidents and Sign-ins
(partials/dashboards/admin/_platform_operations.html) were read as one panel
of loose lines, so the new web app drew them as underlined links. Each is now
a list of rows that names its family (admin-panel), and the cards name the
grid they sit in side by side (admin-ops-grid).
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.mobile_feed import page_blocks

OPS = """
<main>
<div class="admin-ops-grid">
  <section class="admin-panel" aria-labelledby="c">
    <header class="admin-panel__header"><h2 id="c">Critical Now</h2></header>
    <div class="admin-target-row">
      <a href="/admin-ops/incidents/i1">OPS-000006 · Server error on /partners</a>
      <strong>System Incident</strong>
      <a href="/admin-ops/incidents/i1" class="admin-next-step">Acknowledge Incident<span aria-hidden="true"> →</span></a>
    </div>
  </section>
  <section class="admin-panel" aria-labelledby="r">
    <header class="admin-panel__header"><h2 id="r">Recent Incidents</h2></header>
    <div class="admin-target-row">
      <a href="/admin-ops/incidents/i2">INC-000267 · exceeds the 3000ms SLO</a>
      <strong>35×</strong>
      <span class="admin-status s-orange">Open</span>
    </div>
  </section>
  <section class="admin-panel" aria-labelledby="l" data-admin-logins>
    <header class="admin-panel__header">
      <h2 id="l">Sign-ins</h2>
      <span class="edify-text-caption">1 today · 85 this week · 113 in 7 days</span>
    </header>
    <div class="admin-target-row">
      <span>Wed 18 Nov</span>
      <strong>19</strong>
      <span class="admin-presence-bar" aria-hidden="true"><i style="--w: 40%"></i></span>
    </div>
    <div class="admin-target-row admin-target-row--head"><span>Week of</span><strong>Sign-ins</strong><span></span></div>
    <div class="admin-target-row"><span>16 Nov</span><strong>85</strong><span></span></div>
  </section>
  <section class="admin-panel" aria-labelledby="e">
    <header class="admin-panel__header"><h2 id="e">Critical Now</h2></header>
    <p class="admin-panel__empty">Nothing critical is open.</p>
  </section>
</div>
</main>
"""


class AdminPanelCardsTest(SimpleTestCase):
    def setUp(self):
        self.blocks = page_blocks.read(OPS, path="/dashboard", desktop=True)["blocks"]

    def test_each_card_is_a_list_of_its_family_in_its_grid(self):
        self.assertEqual(
            [
                (b["list"]["title"], b["list"]["family"], b["group"])
                for b in self.blocks
            ],
            [
                ("Critical Now", "admin-panel", "admin-ops-grid"),
                ("Recent Incidents", "admin-panel", "admin-ops-grid"),
                ("Sign-ins", "admin-panel", "admin-ops-grid"),
                ("Critical Now", "admin-panel", "admin-ops-grid"),
            ],
        )

    def test_a_row_keeps_its_link_figure_status_and_next_step(self):
        critical, recent = self.blocks[0]["list"], self.blocks[1]["list"]

        self.assertEqual(
            critical["items"],
            [
                {
                    "title": "OPS-000006 · Server error on /partners",
                    "href": "/admin-ops/incidents/i1",
                    "count": "System Incident",
                    "actions": [
                        {
                            "key": "acknowledge_incident",
                            "label": "Acknowledge Incident",
                            "enabled": True,
                            "href": "/admin-ops/incidents/i1",
                        }
                    ],
                }
            ],
        )
        self.assertEqual(
            recent["items"][0]["badges"], [{"text": "Open", "tone": "warning"}]
        )

    def test_sign_ins_keep_their_line_bars_and_the_weeks_heading(self):
        logins = self.blocks[2]["list"]

        self.assertEqual(logins["subtitle"], "1 today · 85 this week · 113 in 7 days")
        self.assertEqual(logins["items"][0]["meter"], {"fraction": 0.4})
        self.assertEqual(
            (
                logins["items"][1]["title"],
                logins["items"][1]["count"],
                logins["items"][1]["tone"],
            ),
            ("Week of", "Sign-ins", "head"),
        )
        self.assertNotIn("href", logins["items"][2])

    def test_an_empty_card_says_so(self):
        self.assertEqual(
            (self.blocks[3]["list"]["items"], self.blocks[3]["list"]["empty"]),
            ([], "Nothing critical is open."),
        )


class CardsInsideAPartTest(SimpleTestCase):
    def test_cards_inside_a_wrapper_are_still_cards(self):
        # The dashboard's Operations part wraps the grid in sections of its
        # own; the wrapper is read inside, not as one panel of lines.
        wrapped = OPS.replace(
            '<div class="admin-ops-grid">',
            '<section class="admin-operations"><div class="admin-ops-grid">',
        ).replace("</main>", "</section></main>")
        blocks = page_blocks.read(wrapped, path="/dashboard", desktop=True)["blocks"]

        self.assertEqual(
            [b["list"]["title"] for b in blocks],
            ["Critical Now", "Recent Incidents", "Sign-ins", "Critical Now"],
        )
