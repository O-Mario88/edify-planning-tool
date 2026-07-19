import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


ROOT = Path(settings.BASE_DIR)


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _production_frontend_files():
    patterns = (
        "templates/**/*.html",
        "static/css/**/*.css",
        "static/js/**/*.js",
        "assets/css/**/*.css",
    )
    for pattern in patterns:
        yield from ROOT.glob(pattern)


def _contrast_ratio(foreground, background):
    def luminance(hex_color):
        values = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in values
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted(
        (luminance(foreground), luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


class PlatformDesignSystemQualityTest(SimpleTestCase):
    def test_inter_is_the_global_and_compiled_ui_font(self):
        base = _read("templates/base.html")
        tokens = _read("static/css/design-system.css")
        compiled = _read("static/css/main.css")

        self.assertIn("family=Inter", base)
        self.assertIn("--edify-font-sans: 'Inter'", tokens)
        self.assertRegex(compiled, r"--font-sans:\s*Inter,")

    def test_no_unapproved_font_family_is_shipped(self):
        forbidden = re.compile(
            r"\b(Outfit|Georgia|Times New Roman|Roboto|Open Sans|Poppins|Montserrat|Arial)\b",
            re.IGNORECASE,
        )
        violations = []
        for path in _production_frontend_files():
            match = forbidden.search(path.read_text(encoding="utf-8"))
            if match:
                violations.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
        self.assertEqual(
            violations, [], "Unapproved UI fonts: " + ", ".join(violations)
        )

    def test_charts_explicitly_use_inter(self):
        charts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "templates").rglob("*.html")
            if "fontFamily" in path.read_text(encoding="utf-8")
        )
        self.assertNotIn("fontFamily: 'Outfit", charts)
        self.assertNotIn('fontFamily: "Outfit', charts)
        self.assertIn("fontFamily: 'Inter", charts)

    def test_shared_cards_stretch_without_an_arbitrary_fixed_height(self):
        # Asserted against platform.css only: it is the stylesheet base.html
        # actually loads. This previously also asserted against
        # edify-components.css, which no template ever referenced — a contract
        # pinned to dead code. That file has since been removed along with
        # edify-pages.css and edify-tokens.css (the latter advertised itself as
        # "THE SINGLE SOURCE OF TRUTH" while shipping values that contradicted
        # the live tokens).
        platform = _read("static/css/platform.css")
        self.assertIn("align-self: stretch", platform)
        self.assertIn("block-size: 100%", platform)
        self.assertNotIn("height: 108px", platform)

    def test_shared_responsive_contract_covers_mobile_and_tablet(self):
        platform = _read("static/css/platform.css")
        self.assertIn("@media (max-width: 63.9375rem)", platform)
        self.assertIn("@media (max-width: 47.5rem)", platform)
        self.assertIn("@media (max-width: 30rem)", platform)
        self.assertIn("platform-table-cards", platform)
        self.assertIn("min-block-size: 2.75rem", platform)

    def test_every_authenticated_page_inherits_compact_cockpit_density(self):
        shell = _read("templates/layouts/shell.html")
        platform = _read("static/css/platform.css")
        tokens = _read("static/css/design-system.css")
        self.assertIn('class="edify-workspace', shell)
        self.assertIn('data-density="compact"', shell)
        self.assertIn('data-analytics-engine="edify-python-1.0"', shell)
        self.assertIn("main.edify-workspace", platform)
        self.assertIn("platform-deferred", platform)
        self.assertIn("contain-intrinsic-size", platform)

    def test_radius_scale_has_one_source_of_truth_at_spec_values(self):
        """The five radius tokens are defined exactly once, at the approved
        geometry (spec §11): surface 12px · control 8px · overlay 16px.

        design-system.css used to re-declare them as 13/9/16/7 and, because it
        loads after main.css, silently won — two competing sources of truth for
        the same geometry, at values matching nothing in the spec. Every card
        and control on the platform rendered a step rounder than approved.
        """
        source = _read("assets/css/tailwind.source.css")
        compiled = _read("static/css/main.css")
        tokens = _read("static/css/design-system.css")

        for declaration in (
            "--radius-surface: 12px",
            "--radius-control: 8px",
            "--radius-overlay: 16px",
        ):
            self.assertIn(declaration, source, f"{declaration} missing from Tailwind source")
            self.assertIn(declaration, compiled, f"{declaration} missing from compiled main.css")

        # No second definition anywhere else in the loaded cascade.
        for token in ("--radius-surface", "--radius-control", "--radius-overlay"):
            self.assertNotIn(
                f"{token}:",
                tokens,
                f"{token} must not be redefined in design-system.css — it is "
                "defined once in assets/css/tailwind.source.css.",
            )


    def test_sign_in_layout_is_not_a_design_system_island(self):
        """The sign-in screen must consume the same token layer as the app.

        It previously loaded login.css alone — no tokens, no shared utilities —
        and had drifted to nine bespoke radii (.95rem, .72rem, 1.5rem, .7rem,
        .78rem, .92rem, .75rem, 999px, 50%) on the first screen every user
        sees. That is the "page-specific design language" §1 forbids.
        """
        layout = _read("templates/layouts/login.html")
        login_css = _read("static/css/login.css")

        self.assertIn("css/main.css", layout)
        self.assertIn("css/design-system.css", layout)

        # Radii come from the token scale. The only literals allowed are the
        # circular spinner and the mobile full-bleed card (both documented).
        literals = re.findall(r"border-radius:\s*([^;]+);", login_css)
        off_system = [
            value.strip()
            for value in literals
            if "var(--radius" not in value and value.strip() not in ("50%", "0")
        ]
        self.assertEqual(
            off_system,
            [],
            f"login.css must use the radius token scale, found: {off_system}",
        )

    def test_dark_workspace_has_accessible_depth_and_primary_actions(self):
        tokens = _read("static/css/design-system.css")
        platform = _read("static/css/platform.css")

        for declaration in (
            "--edify-bg: #000000",
            "--edify-surface: #0d0d0f",
            "--edify-surface-raised: #151518",
            "--edify-surface-hover: #1c1c20",
            "--edify-text: #f5f7fa",
            "--edify-text-muted: #d6dde7",
            "--edify-text-subtle: #aeb9c7",
            "--edify-accent: #2563eb",
            "--edify-warning: #fb923c",
        ):
            self.assertIn(declaration, tokens)

        self.assertGreaterEqual(_contrast_ratio("#f5f7fa", "#0d0d0f"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#d6dde7", "#0d0d0f"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#aeb9c7", "#0d0d0f"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#ffffff", "#2563eb"), 4.5)
        self.assertIn("DARK WORKSPACE — CINEMATIC DEPTH, OPERATIONAL CLARITY", platform)
        self.assertIn(
            "background-image: var(--edify-button-primary-treatment)", platform
        )

    def test_light_workspace_uses_the_approved_edify_reference_treatment(self):
        tokens = _read("static/css/design-system.css")
        platform = _read("static/css/platform.css")
        base = _read("templates/base.html")

        # Spec §5 brand + §6 four-step light surface ladder.
        for declaration in (
            "--edify-brand-primary: #4d7187",
            "--edify-brand-primary-hover: #405e71",
            "--edify-brand-secondary: #ef564b",
            "--edify-bg: #edf1f3",
            "--edify-section-bg: #f2f5f6",
            "--edify-surface: #f8fafb",
            "--edify-surface-raised: #ffffff",
            "--edify-border: #c7d1d7",
            "--edify-text: #17232b",
            "--edify-text-muted: #3f515c",
        ):
            self.assertIn(declaration, tokens)

        # Pure white is the ELEVATED step only — never the canvas or the
        # standard card, or cards dissolve into the page (spec §6).
        self.assertNotIn("--edify-bg: #ffffff", tokens)
        self.assertNotIn("--edify-surface: #ffffff", tokens)

        self.assertIn(
            "Light workspace: the approved Edify sign-in visual language", platform
        )
        self.assertIn(":root:not(.theme-blue):not(.theme-dark)", platform)
        self.assertIn("#edf1f3", base)

    def test_light_workspace_text_hierarchy_meets_high_contrast_standard(self):
        tokens = _read("static/css/design-system.css")
        platform = _read("static/css/platform.css")

        for declaration in (
            "--edify-text: #17232b",
            "--edify-text-muted: #3f515c",
            "--edify-text-subtle: #5f707a",
            "--edify-text-disabled: #6b7b84",
        ):
            self.assertIn(declaration, tokens)

        # Body-text steps clear AA on the card plane they actually sit on.
        # (#6b7b84 is the disabled step, which WCAG exempts from the minimum.)
        for colour in ("#17232b", "#3f515c", "#5f707a"):
            self.assertGreaterEqual(_contrast_ratio(colour, "#f8fafb"), 4.5)
            self.assertGreaterEqual(_contrast_ratio(colour, "#edf1f3"), 4.5)

        # Primary brand must stay legible under white button labels in every
        # interaction state.
        for colour in ("#4d7187", "#405e71", "#385363"):
            self.assertGreaterEqual(_contrast_ratio("#ffffff", colour), 4.5)

        self.assertIn(".text-gray-400, .text-gray-500", platform)
        self.assertIn(".text-slate-300, .text-gray-300", platform)

    def test_recovery_plan_call_to_action_uses_the_shared_primary_treatment(self):
        team_targets = _read("templates/partials/targets/team/body.html")
        pages = _read("static/css/pages.css")

        self.assertIn("tt-button--primary tt-button--recovery", team_targets)
        self.assertIn(".tt-button--recovery", pages)
        self.assertIn("min-height: 3rem", pages)
        self.assertIn("background-image: var(--edify-button-primary-treatment)", pages)

    def test_shared_card_contract_covers_named_feature_surfaces(self):
        tokens = _read("static/css/design-system.css")
        platform = _read("static/css/platform.css")

        for declaration in (
            "--edify-card-surface:",
            "--edify-card-border:",
            "--edify-card-shadow:",
            "--edify-card-backdrop-filter:",
        ):
            self.assertIn(declaration, tokens)

        for selector in (
            '[class*="-card"]:not([class*="-card-"])',
            '[class*="-panel"]:not([class*="-panel-"])',
            '[class*="-kpi"]:not([class*="-kpi-"])',
            ".kpi-strip__item",
            ".spp-empty",
            ".spa-empty",
            ".tt-modal__panel",
            ".theme-blue main :is(",
            ".theme-dark main :is(",
            ".edify-risk-card, .card-alert",
        ):
            self.assertIn(selector, platform)

    def test_kpi_labels_use_the_shared_title_case_contract(self):
        tokens = _read("static/css/design-system.css")
        platform = _read("static/css/platform.css")

        self.assertIn("--edify-kpi-label-weight: 600", tokens)
        self.assertIn("--edify-kpi-label-tracking:", tokens)
        self.assertIn("KPI label typography", platform)
        self.assertIn("text-transform: none !important", platform)

        for template in (
            "templates/partials/professional_development/body.html",
            "templates/partials/hr/pd_dashboard/body.html",
            "templates/pages/ia/analytics_dashboard.html",
            "templates/partials/dashboards/pl/body.html",
            "templates/partials/dashboards/cd/body.html",
            "templates/partials/dashboards/hr/body.html",
            "templates/partials/analytics/cd/body.html",
            "templates/partials/analytics/pl/body.html",
            "templates/partials/analytics/pl/activity_tracking.html",
            "templates/partials/debriefs/dashboard_body.html",
            "templates/partials/targets/my_body.html",
            "templates/partials/finance/country_budget/root.html",
            "templates/pages/reports/index.html",
            "templates/pages/projects/index.html",
            # cluster_card.html no longer belongs here: its SSA intervention
            # scores moved from KPI-style metric cards into the shared
            # partials/ssa/score_group_columns.html grouped-list presentation
            # (normal-case <strong> labels, not the uppercase-tracking KPI
            # label pattern this contract enforces). The KPI-label contract is
            # still enforced for every surface that actually renders KPI cards.
        ):
            self.assertIn("edify-kpi-label", _read(template), template)

        program_lead_dashboard = _read("templates/partials/dashboards/pl/body.html")
        self.assertNotIn(
            'class="text-[12px] font-semibold tracking-[0.06em] uppercase"',
            program_lead_dashboard,
        )

    def test_program_lead_funding_card_is_separate_from_the_urgent_schools_row(self):
        dashboard = _read("templates/partials/dashboards/pl/body.html")
        funding = _read("templates/partials/dashboards/pl/funding_execution.html")
        pages = _read("static/css/pages.css")

        self.assertIn('class="pl-intelligence-grid"', dashboard)
        intelligence_row = dashboard[
            dashboard.index("SSA Intelligence") : dashboard.index("Team Backlog")
        ]
        self.assertNotIn("Funding &amp; Execution", intelligence_row)
        self.assertIn("pl-funding-card pl-funding-card--wide", dashboard)
        self.assertGreater(
            dashboard.index("Funding &amp; Execution"), dashboard.index("Team Backlog")
        )
        self.assertIn("pl-funding-card__body", dashboard)
        self.assertIn("pl-funding-summary", funding)
        self.assertLess(
            funding.index("pl-funding-donut"), funding.index("pl-funding-statuses")
        )
        self.assertIn("container: pl-dashboard / inline-size", pages)
        self.assertIn(
            "grid-template-columns: minmax(0, 0.76fr) minmax(0, 1.64fr)",
            pages,
        )
        self.assertIn("pl-funding-card--wide .pl-funding-card__body", pages)
        self.assertIn("overflow-x: clip", pages)

    def test_program_lead_urgent_schools_card_uses_compact_server_pagination(self):
        dashboard = _read("templates/partials/dashboards/pl/body.html")
        pager = _read("templates/partials/dashboards/pl/urgent_schools_page.html")

        self.assertIn("urgent_pagination.total", dashboard)
        self.assertIn("urgent-schools-content", dashboard)
        self.assertIn("Showing {{ urgent_pagination.first_row }}", pager)
        self.assertIn('hx-get="/dashboard/pl-urgent-schools?', pager)

    def test_operational_analytics_domains_use_the_shared_python_engine(self):
        domain_files = (
            "apps/analytics/ssa_performance_service.py",
            "apps/analytics/decision_engine.py",
            "apps/analytics/impact_engine.py",
            "apps/projects/planning_service.py",
            "apps/projects/my_plan_service.py",
            "apps/projects/impact_service.py",
            "apps/frontend/views/finance_operating_views.py",
            "apps/budget_intelligence/services.py",
        )
        for path in domain_files:
            self.assertIn("platform_engine", _read(path), path)

    def test_every_declared_tab_has_aria_state_and_a_real_panel(self):
        templates = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "templates").rglob("*.html")
        )
        tabs = re.findall(r"<(?:a|button)\b[^>]*\brole=\"tab\"[^>]*>", templates)
        self.assertGreater(len(tabs), 0)
        for tab in tabs:
            self.assertIn("aria-selected=", tab)
            controls = re.search(r'aria-controls="([^"]+)"', tab)
            self.assertIsNotNone(controls, tab)
            self.assertIn(f'id="{controls.group(1)}"', templates)
        self.assertIn('role="tabpanel"', templates)

    def test_tabs_have_shared_keyboard_navigation(self):
        script = _read("static/js/alpine-components.js")
        for key in ("ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"):
            self.assertIn(key, script)
        self.assertIn("htmx:afterSettle", script)

    def test_filter_and_tab_controls_keep_one_canonical_state(self):
        school_tabs = _read("templates/partials/schools/tabs.html")
        school_page = _read("templates/pages/schools/index.html")
        planning_page = _read("templates/pages/planning/index.html")
        planning_tabs = _read("templates/partials/planning/tabs.html")
        my_plan_tabs = _read("templates/partials/my_plan/period_tabs.html")
        messages = _read("templates/pages/messages/index.html")
        analytics = _read("templates/partials/analytics/filters.html")

        self.assertNotRegex(school_tabs, r'hx-get="/schools\?tab=')
        self.assertIn("filters-tab-input", school_tabs)
        self.assertIn('name="per_page"', school_page)
        self.assertIn('hx-push-url="true"', school_page)
        self.assertIn('hx-swap="outerHTML"', planning_page)
        self.assertIn('name="q"', planning_page)
        self.assertIn('role="tablist"', planning_tabs)
        self.assertNotRegex(my_plan_tabs, r'hx-get="/my-plan\?period=')
        self.assertIn("messages-active-tab", messages)
        self.assertNotRegex(messages, r'hx-get="/messages\?tab=')
        self.assertNotIn('hx-get="/analytics?fy=2026&quarter=Q2"', analytics)

    def test_finance_dashboard_does_not_ship_placeholder_tabs_or_actions(self):
        template = _read("templates/pages/accounts/dashboard.html")
        active_template = re.sub(
            r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}",
            "",
            template,
            flags=re.DOTALL,
        )
        self.assertNotIn("activeTab", active_template)
        self.assertNotIn("Documents &amp; Proofs (0)", active_template)
        self.assertNotIn("Disburse Funds\n</button>", active_template)
        self.assertIn("Open Canonical Disbursement Queue", active_template)
        self.assertIn("filteredFunds()", active_template)


class GeometryConsistencyGuardTest(SimpleTestCase):
    """Static guards that keep the approved geometry from drifting back.

    Templates must express radius and elevation through the shared utilities
    (rounded-surface / rounded-control / rounded-overlay / rounded-pill and the
    shadow scale), never as arbitrary Tailwind values or inline styles. Those
    bypass the token layer, so a later change to the canonical scale silently
    skips them — which is exactly how budgets/monthly.html ended up rendering
    five bespoke radii (7/9/10/14/16px) next to the rest of the platform.
    """

    def _templates(self):
        return sorted((ROOT / "templates").rglob("*.html"))

    def test_no_arbitrary_radius_in_templates(self):
        import re

        pattern = re.compile(r"rounded-\[[^\]]*\]")
        offenders = []
        for path in self._templates():
            with open(path, encoding="utf-8", errors="ignore") as handle:
                for lineno, line in enumerate(handle, 1):
                    if pattern.search(line):
                        offenders.append(f"{path}:{lineno}")
        self.assertEqual(
            offenders,
            [],
            "Arbitrary radius values bypass the token scale. Use "
            "rounded-surface (12px) / rounded-control (8px) / rounded-overlay "
            f"(16px) / rounded-pill instead: {offenders}",
        )

    def test_no_arbitrary_shadow_in_templates(self):
        import re

        pattern = re.compile(r"shadow-\[[^\]]*\]")
        offenders = []
        for path in self._templates():
            with open(path, encoding="utf-8", errors="ignore") as handle:
                for lineno, line in enumerate(handle, 1):
                    if pattern.search(line):
                        offenders.append(f"{path}:{lineno}")
        self.assertEqual(
            offenders, [], f"Use the shared shadow scale, not arbitrary values: {offenders}"
        )

    def test_no_inline_border_radius_in_templates(self):
        import re

        pattern = re.compile(r'style="[^"]*border-radius', re.IGNORECASE)
        offenders = []
        for path in self._templates():
            with open(path, encoding="utf-8", errors="ignore") as handle:
                for lineno, line in enumerate(handle, 1):
                    if pattern.search(line):
                        offenders.append(f"{path}:{lineno}")
        self.assertEqual(
            offenders, [], f"Inline border-radius bypasses the token scale: {offenders}"
        )

    def test_no_serif_or_hardcoded_font_family_in_templates(self):
        """Inter is the single UI font; a page must not smuggle in another
        family (budgets/monthly.html previously rendered a group label in
        italic Times New Roman inside an operational table)."""
        import re

        pattern = re.compile(r"font-family\s*:\s*([^;\"'}]+)", re.IGNORECASE)
        offenders = []
        for path in self._templates():
            with open(path, encoding="utf-8", errors="ignore") as handle:
                for lineno, line in enumerate(handle, 1):
                    for value in pattern.findall(line):
                        normalized = value.strip().lower()
                        if "--edify-font" not in normalized and "inter" not in normalized:
                            offenders.append(f"{path}:{lineno} -> {value.strip()[:50]}")
        self.assertEqual(
            offenders,
            [],
            f"Use var(--edify-font-sans); Inter is the only approved UI font: {offenders}",
        )


class StatusColourConsistencyGuardTest(SimpleTestCase):
    """A status label must carry one colour meaning across the whole platform.

    Spec §23: the same status must not appear green on one page and blue on
    another. Colour is how a user reads state at a glance, so a status that
    changes family between screens teaches them that colour means nothing.

    Four labels had drifted when this guard was written -- "Ready" rendered
    emerald on the school list card and indigo in the planning table,
    "Verified" green in the IA workspace and emerald on reimbursements, while
    "Draft" and "Pending" each appeared as both slate and amber. The canonical
    reading is: emerald = done/good, amber = awaiting action, slate = inert or
    not yet started.
    """

    # Families that carry the same meaning to a user; treated as one tone so
    # the guard flags real semantic drift, not a palette nickname.
    SYNONYMS = {
        "green": "emerald",
        "yellow": "amber",
        "red": "rose",
        "gray": "slate",
        "sky": "blue",
    }
    FAMILY = re.compile(
        r"(?:bg|text)-(emerald|green|amber|yellow|rose|red|blue|sky|indigo|"
        r"violet|purple|slate|gray|orange|teal)-\d{2,3}"
    )
    # A short capitalised word inside a pill is a status label, not prose.
    PILL = re.compile(
        r"<span[^>]*rounded-pill[^>]*>\s*([A-Z][A-Za-z /-]{2,26}?)\s*</span>"
    )

    def test_each_status_label_uses_one_colour_family(self):
        seen = {}
        for path in sorted((ROOT / "templates").rglob("*.html")):
            markup = path.read_text(encoding="utf-8", errors="ignore")
            for match in self.PILL.finditer(markup):
                families = {
                    self.SYNONYMS.get(family, family)
                    for family in self.FAMILY.findall(match.group(0))
                }
                if families:
                    label = match.group(1).strip()
                    seen.setdefault(label, {}).setdefault(
                        frozenset(families), []
                    ).append(path.relative_to(ROOT).as_posix())

        conflicts = {
            label: tones for label, tones in seen.items() if len(tones) > 1
        }
        detail = "; ".join(
            f"{label} renders as "
            + " and ".join(
                f"{'+'.join(sorted(tone))} ({', '.join(sorted(files))})"
                for tone, files in tones.items()
            )
            for label, tones in sorted(conflicts.items())
        )
        self.assertEqual(
            conflicts,
            {},
            "The same status must read the same colour everywhere "
            f"(spec §23): {detail}",
        )


class FocusTreatmentConsistencyGuardTest(SimpleTestCase):
    """Keyboard focus must be one brand-derived treatment, not per-theme guesses.

    Spec §32. The focus ring is the only thing a keyboard user has to know
    where they are, so it has to be as deliberate as any other brand surface.

    Both focus tokens now resolve from ``--edify-accent``, so a theme that
    changes its accent gets a matching ring for free. They previously
    disagreed: ``--edify-focus-outline`` used the accent while
    ``--edify-focus-ring`` was hardcoded to a different blue in each of the
    three themes. Those blues were hand-copied accent values -- the blue theme
    had ``rgba(123, 189, 232, .26)`` against an accent of ``#7bbde8``, the same
    colour written twice -- which is exactly the kind of copy that goes stale
    silently when only one of the two is updated.
    """

    # Generated by Tailwind; the sign-in hero keeps its approved palette (§2).
    EXEMPT = {"main.css", "login.css"}
    DEFINITION = re.compile(r"--edify-focus-(?:ring|outline)\s*:\s*([^;]+);")
    LITERAL_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(")

    def test_focus_tokens_are_derived_from_the_accent(self):
        offenders = []
        definitions = 0
        for path in sorted((ROOT / "static" / "css").glob("*.css")):
            if path.name in self.EXEMPT:
                continue
            for match in self.DEFINITION.finditer(
                path.read_text(encoding="utf-8", errors="ignore")
            ):
                definitions += 1
                value = match.group(1).strip()
                if self.LITERAL_COLOUR.search(value):
                    offenders.append(f"{path.name}: {value[:70]}")

        self.assertGreater(
            definitions, 0, "focus token scan matched nothing -- the guard has gone blind"
        )
        self.assertEqual(
            offenders,
            [],
            "Focus tokens must derive from var(--edify-accent) so every theme "
            f"gets a ring that matches its brand colour (spec §32): {offenders}",
        )


class ChartEmptyStateGuardTest(SimpleTestCase):
    """Every chart states an empty result rather than painting a blank box.

    Spec §24, and the platform rule that an empty result is shown honestly
    instead of being dressed up or left ambiguous. A chart with no rows paints
    an empty rectangle by default, which a reader interprets as "still
    loading" or "broken" rather than "nothing happened in this period".

    ApexCharts merges ``window.Apex`` into every instance it creates, so the
    global default is the only thing that reaches all of them. Charts are
    constructed inline in a dozen templates; a per-template message would be
    twelve copies to keep in sync, which is how the status colours drifted.
    """

    def test_charts_declare_a_global_empty_state(self):
        base = _read("templates/base.html")
        self.assertIn(
            "window.Apex",
            base,
            "base.html must define the global ApexCharts defaults -- it is the "
            "only hook that reaches charts built inline in other templates.",
        )
        self.assertIn(
            "noData",
            base,
            "The global ApexCharts defaults must set noData so a chart with no "
            "rows says so instead of rendering as a blank rectangle (spec §24).",
        )
        # The message must be readable copy, not a placeholder or a bare dash.
        self.assertRegex(
            base,
            r"noData:\s*\{[^}]*text:\s*['\"][A-Z][^'\"]{8,}['\"]",
            "The empty-chart message must be a real sentence a reader can act "
            "on, not a placeholder.",
        )
        # It must inherit the muted text token rather than a hardcoded grey.
        self.assertIn(
            "--edify-text-muted",
            base,
            "The empty-chart message must take its colour from the muted text "
            "token so it matches other secondary copy.",
        )


class TemplateCommentLeakGuardTest(SimpleTestCase):
    """Developer notes must not render as page copy.

    Django's ``{# ... #}`` is a single-line construct. Its tokenizer does not
    match across a newline, so a comment wrapped onto a second line stops
    being a comment: the text leaks into the page and the reader sees the
    note. It fails silently -- the template still renders, the tests still
    pass, and only a screenshot shows the paragraph of developer prose sitting
    above the content.

    Five had accumulated when this guard was written, two of them inside
    ``{% for %}`` loops on the cluster detail page, so the note repeated once
    per intervention. Multi-line notes belong in ``{% comment %}``.
    """

    def test_no_multiline_hash_comment_leaks_into_rendered_output(self):
        offenders = []
        for path in sorted((ROOT / "templates").rglob("*.html")):
            markup = path.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r"\{#", markup):
                rest = markup[match.start():]
                close = rest.find("#}")
                if close == -1:
                    continue
                if "\n" in rest[:close]:
                    line = markup[: match.start()].count("\n") + 1
                    offenders.append(
                        f"{path.relative_to(ROOT).as_posix()}:{line}"
                    )
        self.assertEqual(
            offenders,
            [],
            "Django's {# #} comment does not span newlines, so these render as "
            "visible page text. Use {% comment %}...{% endcomment %} for "
            f"multi-line notes: {offenders}",
        )
