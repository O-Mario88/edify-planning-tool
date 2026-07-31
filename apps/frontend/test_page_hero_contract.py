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
    "templates/pages/ia/verification_queue.html",
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
    def test_every_named_hero_family_uses_the_flat_surface_contract(self):
        css = BRIDGE.read_text(encoding="utf-8")

        for selector in NAMED_HERO_FAMILIES:
            with self.subTest(selector=selector):
                self.assertIn(selector, css)

        contract = css.split("PAGE HEROES: CONTENT ON THE PAGE CANVAS", 1)[1]
        self.assertIn("background: transparent !important", contract)
        self.assertIn("border: 0 !important", contract)
        self.assertIn("border-radius: 0 !important", contract)
        self.assertIn("box-shadow: none !important", contract)
        self.assertIn("backdrop-filter: none !important", contract)

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
            hero_tag = source[hero_start : source.index(">", hero_start)]

            with self.subTest(template=relative_path):
                self.assertIn("edify-page-hero", hero_tag)
                for token in forbidden_surface_tokens:
                    self.assertNotIn(token, hero_tag)

    def test_card_era_inverse_copy_is_retokenized_for_the_page_canvas(self):
        css = BRIDGE.read_text(encoding="utf-8")
        contract = css.split("PAGE HEROES: CONTENT ON THE PAGE CANVAS", 1)[1]

        self.assertIn("color: var(--edify-text) !important", contract)
        self.assertIn("color: var(--edify-text-muted) !important", contract)
        self.assertIn(".ia-hero .ia-button--primary", contract)
        self.assertIn(".ia-hero .ia-button--secondary", contract)
