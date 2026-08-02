"""Platform-wide page hero surface contract."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "static" / "css" / "consistency.css"

LEGACY_HERO_TEMPLATES = (
    "templates/partials/finance/monthly_request/root.html",
    "templates/pages/accounts/accountability.html",
    "templates/pages/accounts/approval_history.html",
    "templates/pages/accounts/audit_log.html",
    "templates/pages/accounts/batch_payments.html",
    "templates/pages/accounts/blocked.html",
    "templates/pages/accounts/cleared.html",
    "templates/pages/accounts/partner_payments.html",
    "templates/pages/accounts/ready_for_advance.html",
    "templates/pages/accounts/reimbursements.html",
    "templates/pages/accounts/returned.html",
    "templates/pages/accounts/variance_review.html",
    "templates/pages/accounts/weekly_requests.html",
    "templates/pages/analytics/publishing_status.html",
    "templates/pages/budgets/monthly.html",
    "templates/pages/closure/activity_timeline.html",
    "templates/pages/closure/blocked_closure.html",
    "templates/pages/closure/completed_activities.html",
    "templates/pages/closure/readiness_queue.html",
    "templates/pages/finance/country_budget_history.html",
    "templates/pages/finance/country_budget_submission.html",
    "templates/pages/finance/fund_allocation.html",
    "templates/pages/ia/compare_evidence.html",
    "templates/pages/ia/duplicate_review.html",
    "templates/pages/ia/notifications.html",
    "templates/pages/ia/returned_activities.html",
    "templates/pages/ia/verification_history.html",
    # verification_queue.html is gone from this list: the 2026-07-31
    # consistency pass migrated it off the legacy page-hero family onto the
    # canonical `edify-page-header`. Anything migrated should leave here, so
    # the list shrinks as the seventeen header families are consolidated.
    "templates/pages/profile/index.html",
    "templates/pages/staff/detail.html",
)

NAMED_HERO_FAMILIES = (
    ".edify-page-header",
    ".platform-page-header",
    ".platform-hero",
    ".ia-hero",
    ".help-center-hero",
    ".help-shell__header",
    ".hcos-hero",
    ".sp-page-header",
    ".pto-header",
    ".tt-page-header",
    ".calendar-workspace__header",
    ".partner-workspace__header",
    ".admin-command__header",
    ".pd-page-header",
    ".sp-plan__header",
    ".spp-header",
    ".spa-header",
)


class PageHeroSurfaceContractTest(SimpleTestCase):
    def test_every_named_hero_family_uses_the_canonical_header_surface(self):
        """One surface for every header family, and it is the tonal one.

        This asserted the opposite — transparent, no border, no radius, no
        shadow — which was right while the goal was removing heavy header
        cards. It had a side effect nobody had reason to notice: the one
        header the platform actually wanted, the Program Lead Dashboard's
        quiet tonal band, could not be shared, because this bridge flattened
        any page that adopted it.

        The bridge now applies the canonical surface instead of stripping it,
        so these sixteen families converge on one appearance rather than on
        no appearance. backdrop-filter stays stripped: a blur behind a surface
        this close in tone to the canvas buys nothing and costs a compositor
        layer per page.
        """
        css = BRIDGE.read_text(encoding="utf-8")

        for selector in NAMED_HERO_FAMILIES:
            with self.subTest(selector=selector):
                self.assertIn(selector, css)

        contract = css.split("PAGE HEROES: CONTENT ON THE PAGE CANVAS", 1)[1]
        self.assertIn("background: var(--page-header-surface) !important", contract)
        self.assertIn(
            "border: 1px solid var(--page-header-border) !important", contract
        )
        self.assertIn("var(--page-header-radius", contract)
        self.assertIn("box-shadow: var(--page-header-shadow) !important", contract)
        # Still stripped, for the reason in the docstring.
        self.assertIn("backdrop-filter: none !important", contract)

    def test_the_canonical_surface_is_defined_for_every_theme(self):
        """A token referenced by an !important bridge and defined in only one
        theme would leave the other themes with no header surface at all."""
        design_system = (ROOT / "static/css/design-system.css").read_text(
            encoding="utf-8"
        )
        self.assertGreaterEqual(
            design_system.count("--page-header-surface:"),
            3,
            "light, blue and dark each need the surface token",
        )
        for token in (
            "--page-header-border:",
            "--page-header-shadow:",
            "--page-header-radius:",
        ):
            with self.subTest(token=token):
                self.assertIn(token, design_system)

    def test_legacy_dark_hero_cards_are_migrated_to_the_shared_marker(self):
        forbidden_surface_tokens = (
            "bg-slate-900",
            "border-slate-800",
            "rounded-surface",
            "shadow-md",
            "shadow-sm",
            "text-white",
        )

        for relative_path in LEGACY_HERO_TEMPLATES:
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            hero_start = source.index("edify-page-hero")
            tag_start = source.rfind("<", 0, hero_start)
            hero_tag = source[tag_start : source.index(">", hero_start)]

            with self.subTest(template=relative_path):
                self.assertIn("edify-page-hero", hero_tag)
                self.assertIn("edify-page-header", hero_tag)
                for token in forbidden_surface_tokens:
                    self.assertNotIn(token, hero_tag)

    def test_card_era_inverse_copy_is_retokenized_for_the_page_canvas(self):
        css = BRIDGE.read_text(encoding="utf-8")
        contract = css.split("PAGE HEROES: CONTENT ON THE PAGE CANVAS", 1)[1]

        self.assertIn("color: var(--edify-text) !important", contract)
        self.assertIn("color: var(--edify-text-muted) !important", contract)
        self.assertIn(".ia-hero .ia-button--primary", contract)
        self.assertIn(".ia-hero .ia-button--secondary", contract)
