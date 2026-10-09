"""Phone heading rows, page-header actions and the cluster card's inset.

Owner, 2026-10-09: "fix the mobile card padding. look at mobile screen cluster
page padding"; "fix the profile mobile design. there is a lot of wrapping and
misallocation of buttons"; "check add school button on what is on that page
and fix any issues like that".

Three rules written at different times met on a phone:

* the cluster card went flush while a phone rule still took its row's inline
  padding away, so every word sat on the card's border;
* "a title beside one action keeps the row" also caught a title beside a
  GROUP of actions that fills its line, leaving the title no width: "Add
  Schools to Cluster" lay over "Schools in This Cluster";
* a page header's actions were held to their own width with the weight of an
  id, so the row marked to be filled stayed ragged.

The layout itself is measured in the browser; this keeps the three rules and
the mark they read from being dropped by a later tidy-up.
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class PhoneHeadRowsContractTest(SimpleTestCase):
    def test_the_cluster_cards_row_keeps_the_cards_inset(self):
        css = _read("static/css/platform.css")
        rule = css.split(
            ".cluster-card .cluster-card__summary[data-row-disclosure-summary] {"
        )[1].split("}")[0]
        self.assertIn("padding-inline: var(--edify-card-inset) !important", rule)

    def test_a_title_above_a_filled_group_has_its_own_line(self):
        css = _read("static/css/components/interactions.css")
        self.assertIn(
            "main .edify-head-row--action.edify-head-row--action"
            "[data-edify-head-stack]:nth-child(n) {\n    flex-wrap: wrap !important;",
            css,
        )
        self.assertIn(
            "[data-edify-head-stack] > .edify-head-row__title"
            ".edify-head-row__title:nth-child(n) {\n    flex: 1 1 100% !important;",
            css,
        )
        script = _read("static/js/micro-ux.js")
        self.assertIn("setAttribute('data-edify-head-stack', '')", script)
        self.assertIn("removeAttribute('data-edify-head-stack')", script)

    def test_page_header_actions_share_a_filled_row(self):
        css = _read("static/css/components/interactions.css")
        self.assertIn(
            "main .edify-page-header > [data-edify-fill]"
            ":not(.edify-page-header__lead):not(form):not(nav):not(details) > "
            ":is(#edify-header-action, a, button, .btn, .edify-action-button, "
            "details > summary) {\n    flex: 1 1 auto !important;",
            css,
        )
