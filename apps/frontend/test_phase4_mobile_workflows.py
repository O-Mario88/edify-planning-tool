"""Contracts for Phase 4 mobile workflow-family architecture."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class PhaseFourMobileWorkflowContractTest(SimpleTestCase):
    def test_workday_pages_opt_into_one_shared_family(self):
        pages = (
            "templates/pages/planning/index.html",
            "templates/pages/my_plan/index.html",
            "templates/pages/calendar/index.html",
            "templates/pages/todos/index.html",
        )
        for path in pages:
            with self.subTest(path=path):
                self.assertIn('data-mobile-family="workday"', _read(path))

    def test_planning_and_my_plan_put_decisions_before_metrics(self):
        planning = _read("templates/pages/planning/index.html")
        my_plan = _read("templates/partials/my_plan/workspace.html")
        todos = _read("templates/pages/todos/index.html")

        self.assertLess(
            planning.index("right_panel.html"), planning.index("kpi_strip_items")
        )
        self.assertLess(
            my_plan.index("priority_queue.html"), my_plan.index("kpi_cards.html")
        )
        self.assertLess(
            todos.index("todos-mobile-next-title"),
            todos.index("Work requiring attention"),
        )

    def test_directories_share_search_filter_and_record_family_rules(self):
        pages = (
            "templates/pages/schools/index.html",
            "templates/pages/clusters/index.html",
            "templates/pages/partners/index.html",
            "templates/pages/projects/index.html",
            "templates/pages/staff/index.html",
        )
        for path in pages:
            with self.subTest(path=path):
                self.assertIn('data-mobile-family="directory"', _read(path))

        styles = _read("static/css/components/mobile-patterns.css")
        self.assertIn(".school-filters-form", styles)
        self.assertIn("repeat(2, minmax(0, 1fr))", styles)
        self.assertIn(".mobile-family-filter", styles)
        self.assertIn("#kpi-cards-row", styles)
        self.assertIn("Directory filters", _read("templates/pages/schools/index.html"))

    def test_finance_and_verification_pages_use_stacked_record_contract(self):
        finance = (
            "templates/pages/accounts/ready_for_advance.html",
            "templates/pages/accounts/accountability.html",
            "templates/pages/accounts/partner_payments.html",
            "templates/pages/accounts/returned.html",
        )
        verification = (
            "templates/pages/ia/verification_queue.html",
            "templates/pages/ia/review_workspace.html",
            "templates/pages/evidence/index.html",
            "templates/pages/ssa/verification_queue.html",
        )
        for path in finance:
            with self.subTest(path=path):
                self.assertIn('data-mobile-family="finance"', _read(path))
        for path in verification:
            with self.subTest(path=path):
                self.assertIn('data-mobile-family="verification"', _read(path))

        styles = _read("static/css/components/mobile-patterns.css")
        self.assertIn(".edify-record-table > tbody > tr", styles)
        self.assertIn("min-block-size: 2.75rem", styles)

    def test_review_workspace_keeps_mobile_decisions_sticky(self):
        review = _read("templates/pages/ia/review_workspace.html")
        self.assertIn("lg:hidden fixed inset-x-0 bottom-0", review)
        self.assertIn('form="verify-form"', review)
        self.assertIn("Clear Activity", review)
        self.assertIn("Return", review)
