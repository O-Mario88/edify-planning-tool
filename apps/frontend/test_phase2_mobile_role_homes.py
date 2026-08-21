"""Static contracts for Phase 2 task-first operational role homes."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class PhaseTwoMobileRoleHomeContractTest(SimpleTestCase):
    ROLE_TEMPLATES = (
        "templates/pages/dashboards/cceo.html",
        "templates/pages/dashboards/pl.html",
        "templates/pages/ia/analytics_dashboard.html",
        "templates/pages/accounts/dashboard.html",
        "templates/pages/partner/today.html",
        "templates/pages/dashboards/main.html",
    )

    def test_each_operational_role_uses_shared_mobile_role_home(self):
        for path in self.ROLE_TEMPLATES:
            with self.subTest(path=path):
                source = _read(path)
                self.assertIn("components/mobile_role_home.html", source)
                self.assertIn("mobile_primary_action", source)

    def test_task_queues_precede_mobile_metrics(self):
        cceo = _read("templates/pages/dashboards/cceo.html")
        ia = _read("templates/pages/ia/analytics_dashboard.html")
        accounts = _read("templates/pages/accounts/dashboard.html")
        partner = _read("templates/pages/partner/today.html")

        self.assertLess(
            cceo.index("cceo-mobile-next-title"),
            cceo.index('title="Week at a glance"'),
        )
        self.assertLess(
            ia.index("ia-mobile-queue-title"),
            ia.index('title="Verification workload"'),
        )
        self.assertLess(
            accounts.index("accounts-mobile-queue-title"),
            accounts.index('title="Finance headline"'),
        )

    def test_desktop_headers_are_suppressed_only_on_mobile(self):
        styles = _read("static/css/components/mobile-patterns.css")
        self.assertIn("@media (max-width: 63.999rem)", styles)
        self.assertIn(".mobile-home-hide", styles)
        self.assertIn("display: none !important", styles)

        for path in self.ROLE_TEMPLATES:
            with self.subTest(path=path):
                self.assertIn("mobile-home-hide", _read(path))

    def test_admin_platform_pulse_precedes_critical_now_on_mobile(self):
        admin = _read("templates/pages/dashboards/main.html")
        self.assertLess(
            admin.index("dashboard_kpi_title"),
            admin.index("admin-mobile-critical-title"),
        )

    def test_responsive_role_pages_do_not_duplicate_the_kpi_dom(self):
        for path in (
            "templates/pages/dashboards/cceo.html",
            "templates/pages/ia/analytics_dashboard.html",
            "templates/pages/dashboards/main.html",
        ):
            with self.subTest(path=path):
                self.assertEqual(_read(path).count("components/kpi_strip.html"), 1)

    def test_role_views_select_real_permission_scoped_primary_actions(self):
        dashboard = _read("apps/frontend/views/dashboard_views.py")
        ia = _read("apps/frontend/views/ia_views.py")
        accounts = _read("apps/frontend/views/finance_operating_views.py")
        partner = _read("apps/frontend/views/partner_views.py")

        self.assertIn('"mobile_primary_action": mobile_primary_action', dashboard)
        self.assertIn('queue_items[0]["review_url"]', ia)
        self.assertIn('"url": "/disbursements" if all_funds', accounts)
        # The partner home is Assigned Activities (2026-08-20); its primary
        # action is permission-scoped scheduling work.
        self.assertIn("def partner_assignments_view", partner)
        self.assertIn('"label": "Schedule assigned work"', partner)

    def test_mobile_agenda_reuses_existing_queue_shapes(self):
        agenda = _read("templates/components/mobile_agenda_card.html")
        self.assertIn("item.activity item.school item.cluster", agenda)
        self.assertIn("item.location item.where item.district item.purpose", agenda)
        self.assertIn("item.date item.due item.planned_date", agenda)
