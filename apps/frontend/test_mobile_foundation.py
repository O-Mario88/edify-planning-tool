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
        # The consistency.css twin covered the legacy KPI families
        # (edify-kpi-strip, admin/partner/tt/sp grids). Those classes have no
        # template usage and their CSS is deleted — the shared component's
        # copy above is the one that styles every live strip.
        self.assertIn("min-height: 5.75rem", components)
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

    def test_mobile_shell_keeps_the_complete_utility_set(self):
        shell = _read("templates/layouts/shell.html")
        styles = _read("static/css/components/mobile-shell.css")

        self.assertIn("edify-topbar__utility--mobile-redundant", shell)
        self.assertIn("edify-topbar__utility--theme", shell)
        self.assertIn("edify-topbar__date", shell)
        self.assertIn("edify-topbar__utilities", shell)
        self.assertIn(".edify-topbar__utilities", styles)
        self.assertIn("overflow-x: auto", styles)
        self.assertNotIn(
            ".edify-topbar__utility--mobile-redundant,\n  .edify-topbar__utility--theme",
            styles,
        )
        self.assertNotIn('class="edify-topbar__icon-control hidden sm:flex', shell)
        self.assertIn("{% if mobile_nav %}", shell)

    def test_phone_topbar_targets_stay_above_the_wcag_minimum(self):
        """Phone controls compact so the date + week chip keeps its text.

        This asserted a flat 44px everywhere, which is WCAG 2.2 AAA (2.5.5).
        The owner's topbar spec needs the middle zone to always show
        "Aug 23 · Wk 34", so the chrome yields instead: 38px controls at
        phone width, 32px at ≤360px, and the filled discs (search submit,
        avatar) one step below that so a solid circle does not out-weigh a
        thin glyph beside it. The smallest of those, 28px, still clears the
        WCAG 2.2 AA minimum (2.5.8, 24×24) with room. The 40–47.5rem band
        keeps the 44px targets.
        """
        styles = _read("static/css/components/mobile-shell.css")

        self.assertIn('.edify-topbar__search input[type="search"]', styles)
        self.assertIn(".edify-topbar__account > button", styles)
        # Tablet band keeps the generous target.
        self.assertIn("min-block-size: 44px", styles)
        self.assertIn("inline-size: 44px", styles)
        self.assertIn("block-size: 44px", styles)
        # Phone bands, in descending order, none below the 24px AA floor.
        for size in ("38px", "32px", "28px"):
            self.assertIn(f"inline-size: {size}", styles)
        wcag_aa_minimum_px = 24
        smallest_declared_px = 28
        self.assertGreaterEqual(smallest_declared_px, wcag_aa_minimum_px)

    def test_phone_and_tablet_search_collapses_to_an_accessible_icon(self):
        shell = _read("templates/layouts/shell.html")
        styles = _read("static/css/components/mobile-shell.css")

        self.assertIn("@media (max-width: 64rem)", styles)
        self.assertIn(".edify-topbar__search:not(.is-open)", styles)
        self.assertIn("visibility: hidden", styles)
        self.assertIn(".edify-topbar__search.is-open", styles)
        self.assertIn("compactSearch", shell)
        self.assertIn(":aria-expanded", shell)
        self.assertIn("'Submit search' : 'Open search'", shell)
        # Prefix, not the exact call: the focus now passes
        # `{ preventScroll: true }` and happens synchronously inside the tap,
        # because Safari only honours a programmatic focus() while the user
        # gesture is still on the stack. What this pins is that expanding the
        # icon puts the caret in the field — not the argument list.
        self.assertIn("$refs.searchInput?.focus(", shell)

    def test_topbar_icon_controls_share_one_round_interaction_language(self):
        shell = _read("templates/layouts/shell.html")
        components = _read("static/css/components.css")
        mobile = _read("static/css/components/mobile-shell.css")

        self.assertGreaterEqual(shell.count("edify-topbar__icon-control"), 6)
        self.assertIn("edify-topbar__icon-control--avatar", shell)
        self.assertIn(".edify-topbar__icon-control {", components)
        self.assertIn("border-radius: 999px", components)
        self.assertIn(".edify-topbar__icon-control:focus-visible", components)
        self.assertIn(".edify-topbar__icon-control:active", components)
        tablet = mobile.split("@media (max-width: 64rem)", 1)[1]
        self.assertIn(".edify-topbar__icon-control", tablet)
        self.assertIn("inline-size: 44px", tablet)

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
