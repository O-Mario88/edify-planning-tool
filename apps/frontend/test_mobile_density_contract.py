import re
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _cache_buster(base: str, asset: str) -> str:
    """The ?v= token base.html serves one asset under, or "" if it has none.

    Pinning the literal token made every stylesheet edit red these tests while
    proving nothing about them: a hard-coded string cannot tell whether two
    assets that must ship together actually match, and it goes stale the moment
    anyone bumps it. What the tests are named for is the pairing, so that is
    what they now read.
    """
    match = re.search(re.escape(asset) + r"' %\}\?v=([A-Za-z0-9._-]+)", base)
    return match.group(1) if match else ""


class MobileDensityContractTests(SimpleTestCase):
    def test_desktop_lists_and_actions_use_compact_density_scale(self):
        css = (ROOT / "static/css/components/mobile-micro-ux.css").read_text()

        self.assertIn("@media (min-width: 64rem)", css)
        self.assertIn("--edify-desktop-list-title-size: 0.9375rem", css)
        self.assertIn("--edify-desktop-list-icon-size: 2rem", css)
        self.assertIn("--edify-action-button-block-size: 2rem", css)
        self.assertIn("--edify-action-button-icon-size: 0.875rem", css)
        self.assertIn("padding: 0.625rem 0.875rem !important", css)

    def test_shared_mobile_controls_use_compact_accessible_scale(self):
        css = (ROOT / "static/css/components/mobile-micro-ux.css").read_text()

        self.assertIn("--edify-action-button-block-size: 2.25rem", css)
        self.assertIn("--edify-action-button-block-size: 1.875rem", css)
        self.assertIn("--edify-action-button-block-size: 1.75rem", css)
        self.assertIn("max-width: 22.5rem", css)
        self.assertEqual(css.count(":root:root:root"), 4)
        self.assertIn(
            "min-block-size: var(--edify-action-button-block-size) !important", css
        )
        self.assertIn("height: var(--edify-action-button-block-size) !important", css)
        self.assertIn('.edify-shell [role="tab"]', css)
        self.assertIn(
            '.edify-shell :where(button, [role="button"], summary, [role="tab"])', css
        )
        self.assertIn('[class~="min-h-9"]', css)
        self.assertIn("font-size: var(--edify-text-micro-size) !important", css)

    def test_platform_typography_uses_one_responsive_semantic_scale(self):
        css = (ROOT / "static/css/components/mobile-micro-ux.css").read_text()

        self.assertIn("--edify-text-display-size: 1.5rem", css)
        self.assertIn("--edify-text-display-size: 1.375rem", css)
        self.assertIn("--edify-text-display-size: 1.25rem", css)
        self.assertIn("--edify-text-body-size: 0.8125rem", css)
        self.assertIn('[class~="text-[18px]"]', css)
        self.assertIn(":not(input, select, textarea)", css)
        self.assertIn("font-size: var(--edify-text-body-size) !important", css)

    def test_mobile_list_titles_are_compact_and_limited_to_two_lines(self):
        css = (ROOT / "static/css/components/mobile-micro-ux.css").read_text()
        cluster = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()

        self.assertIn("--edify-mobile-list-title-size: 0.8125rem", css)
        self.assertIn("-webkit-line-clamp: 2", css)
        self.assertIn("line-clamp: 2", css)
        self.assertIn("[data-record-title]", css)
        self.assertIn("data-list-title", cluster)

    def test_mobile_cluster_card_keeps_name_and_actions_on_one_row(self):
        cluster = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()
        css = (ROOT / "static/css/platform.css").read_text()

        self.assertIn('class="cluster-card__summary"', cluster)
        self.assertNotIn("flex flex-col md:flex-row", cluster)
        self.assertIn('class="cluster-card__actions"', cluster)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto", css)
        self.assertIn("container: cluster-card / inline-size", css)

    def test_mobile_cluster_card_matches_school_record_detail_rhythm(self):
        cluster = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()
        css = (ROOT / "static/css/platform.css").read_text()

        self.assertIn("school-record-row__metadata cluster-card__metadata", cluster)
        self.assertNotIn("cluster-card__facts", cluster)
        self.assertNotIn("cluster-card__readiness", cluster)
        self.assertNotIn("cluster-card__next-action", cluster)
        self.assertNotIn("school-record-row__select", cluster)
        self.assertNotIn("school-record-row__icon", cluster)
        self.assertNotIn('type="checkbox"', cluster)
        self.assertLess(
            cluster.index("cluster-card__metadata"),
            cluster.index("cluster-ssa-summary"),
        )
        self.assertLess(
            cluster.index("cluster-ssa-summary"), cluster.index("expanded-schools-")
        )
        self.assertIn("@container cluster-card (max-width: 30rem)", css)
        self.assertIn("grid-template-columns: max-content minmax(0, 1fr)", css)
        self.assertNotIn("gap-2 md:gap-4", cluster)

    def test_oversight_pages_opt_into_shared_mobile_density(self):
        for name in (
            "team_planning.html",
            "country_planning.html",
            "partner_oversight.html",
        ):
            page = (ROOT / "templates/pages/oversight" / name).read_text()
            self.assertIn('data-mobile-family="oversight"', page)

    def test_mobile_density_stylesheet_cache_key_is_current(self):
        base = (ROOT / "templates/base.html").read_text()

        self.assertNotEqual(_cache_buster(base, "mobile-micro-ux.css"), "")
