"""Contracts for the task-first mobile UI foundation introduced in Phase 1."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class MobileFoundationContractTest(SimpleTestCase):
    def test_base_loads_mobile_patterns_and_behavior_after_core_components(self):
        base = _read("templates/base.html")
        self.assertIn("css/components/mobile-patterns.css", base)
        self.assertIn("js/mobile-ux.js", base)
        self.assertLess(
            base.index("css/components/mobile-shell.css"),
            base.index("css/components/mobile-patterns.css"),
        )

    def test_phone_kpis_are_compact_without_horizontal_scroll(self):
        components = _read("static/css/components.css")
        consistency = _read("static/css/consistency.css")
        template = _read("templates/components/kpi_strip.html")
        compact_grid = "grid-template-columns: repeat(2, minmax(0, 1fr)) !important"

        self.assertIn(compact_grid, components)
        self.assertIn(compact_grid, consistency)
        self.assertIn("min-height: 5.75rem", components)
        self.assertIn("min-block-size: 5.75rem !important", consistency)
        self.assertIn("last-child:nth-child(odd)", components)
        self.assertIn("data-mobile-summary", template)
        self.assertIn('<h2 class="kpi-strip__title">', template)
        self.assertNotIn('<h4 class="kpi-strip__title">', template)
        self.assertNotIn("scroll-snap-type: inline mandatory", components)

    def test_filter_sheet_uses_native_dialog_and_safari_fallback(self):
        template = _read("templates/components/mobile_filter_sheet.html")
        behavior = _read("static/js/mobile-ux.js")

        self.assertIn("<dialog", template)
        self.assertIn('closedby="any"', template)
        self.assertIn("aria-labelledby", template)
        self.assertIn("dialog.showModal()", behavior)
        self.assertIn("'closedBy' in HTMLDialogElement.prototype", behavior)
        self.assertIn("restoreDialogFocus", behavior)

    def test_shared_mobile_patterns_exist_and_keep_native_semantics(self):
        expected = {
            "templates/components/mobile_role_home.html": "data-mobile-role-home",
            "templates/components/mobile_agenda_card.html": "<article",
            "templates/components/mobile_record_card.html": "<article",
            "templates/components/mobile_section_picker.html": "<details",
            "templates/components/mobile_sticky_action_bar.html": "<aside",
        }
        for path, marker in expected.items():
            with self.subTest(path=path):
                self.assertIn(marker, _read(path))

    def test_mobile_shell_removes_redundant_phone_utilities_only(self):
        shell = _read("templates/layouts/shell.html")
        styles = _read("static/css/components/mobile-shell.css")

        self.assertIn("edify-topbar__utility--mobile-redundant", shell)
        self.assertIn("edify-topbar__utility--theme", shell)
        self.assertIn(".edify-topbar__utility--mobile-redundant", styles)
        self.assertIn(".edify-topbar__utility--theme", styles)
        self.assertIn("{% if mobile_nav %}", shell)

    def test_phone_topbar_targets_are_at_least_44_pixels(self):
        styles = _read("static/css/components/mobile-shell.css")

        self.assertIn('.edify-topbar__search input[type="search"]', styles)
        self.assertIn(".edify-topbar__account > button", styles)
        self.assertIn("min-block-size: 44px", styles)
        self.assertIn("inline-size: 44px", styles)
        self.assertIn("block-size: 44px", styles)

    def test_long_page_deferral_is_explicit_and_layout_stable(self):
        styles = _read("static/css/components/mobile-patterns.css")
        self.assertIn("@supports (content-visibility: auto)", styles)
        self.assertIn(".mobile-deferred", styles)
        self.assertIn("contain-intrinsic-size", styles)

    def test_measurement_hooks_are_private_and_endpoint_free(self):
        behavior = _read("static/js/mobile-ux.js")
        self.assertIn("edify:mobile-ux", behavior)
        self.assertIn("first-action-ready", behavior)
        self.assertIn("scroll-depth", behavior)
        self.assertNotIn("sendBeacon", behavior)
        self.assertNotIn("fetch(", behavior)
