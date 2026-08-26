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
        for path in ROOT.glob(pattern):
            # vendor/ holds self-hosted third-party assets — the htmx, Alpine,
            # ApexCharts and FullCalendar bundles, Leaflet's stylesheet. They
            # name fonts we do not use (ApexCharts defaults a label to Arial,
            # Leaflet to Helvetica) and the design-system rules are about code
            # we author. Linting vendored bytes produces noise, or worse, a
            # temptation to edit them — and an edited vendor asset cannot be
            # re-fetched or upgraded cleanly.
            if "/vendor/" in path.as_posix():
                continue
            yield path


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
    def test_geist_sans_is_the_global_and_compiled_ui_font(self):
        base = _read("templates/base.html")
        theme = _read("assets/css/_theme.css")
        tokens = _read("static/css/design-system.css")
        compiled = _read("static/css/main.css")
        bridge = _read("static/css/consistency.css")

        self.assertIn("css/fonts.css", base)
        self.assertIn("--edify-font-sans: 'Geist Sans'", tokens)
        self.assertIn("--font-mono: var(--font-sans);", theme)
        self.assertIn("--edify-font-mono: var(--edify-font-sans);", tokens)
        self.assertRegex(compiled, r'--font-sans:\s*"Geist Sans",')
        self.assertIn("--font-mono: var(--font-sans);", compiled)
        self.assertIn(".leaflet-container {", bridge)
        self.assertIn("font-family: var(--edify-font-sans) !important;", bridge)

    def test_geist_sans_is_self_hosted_on_every_entry_point(self):
        """The typeface must not depend on a third-party request.

        Every type token is measured against Geist Sans metrics, so a third-party
        request that is slow or blocked rendered the whole product in
        ui-sans-serif at Geist Sans measurements — the same CSS looking correct
        locally and wrong in production on one cross-origin fetch.

        This once asserted a font family was present in base.html, which passed on
        the CDN link that WAS the problem.
        """
        faces = _read("static/css/fonts.css")
        self.assertIn("@font-face", faces)
        self.assertIn("Geist-Variable.woff2", faces)
        self.assertIn("Geist-Italic-Variable.woff2", faces)
        self.assertTrue((ROOT / "static/fonts/Geist-Variable.woff2").is_file())
        self.assertTrue((ROOT / "static/fonts/Geist-Italic-Variable.woff2").is_file())

        # Relative, so ManifestStaticFilesStorage can rewrite it to the hashed
        # filename during collectstatic.
        self.assertNotIn('url("/static/', faces)

        entry_points = [
            "templates/base.html",
            "templates/layouts/login.html",
            "templates/pages/help/print_article.html",
            "templates/pages/help/manual_export.html",
        ]
        missing = [p for p in entry_points if "css/fonts.css" not in _read(p)]
        self.assertEqual(
            missing, [], f"entry points not loading the typeface: {missing}"
        )

        for entry_point in ("templates/base.html", "templates/layouts/login.html"):
            source = _read(entry_point)
            self.assertIn("fonts/Geist-Variable.woff2", source)
            self.assertNotIn("InterVariable.woff2", source)

    def test_no_template_fetches_a_font_from_a_third_party(self):
        offenders = []
        for path in (ROOT / "templates").rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            if "fonts.googleapis.com" in text or "fonts.gstatic.com" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(
            offenders,
            [],
            "Geist Sans is self-hosted; these still request fonts over the network: "
            + ", ".join(offenders),
        )

    def test_no_unapproved_font_family_is_shipped(self):
        forbidden = re.compile(
            r"\b(Inter|Outfit|Georgia|Times New Roman|Roboto|Open Sans|Poppins|Montserrat|Arial)\b",
            re.IGNORECASE,
        )
        # Tailwind's preflight writes `font-family: var(--default-font-family,
        # <generic stack>)`, and from 4.3.3 that stack is spelled out inline —
        # -apple-system, Segoe UI, Roboto, Arial and the rest. It is a fallback
        # for a variable the bundle defines two lines earlier as var(--font-sans),
        # which is Geist Sans, so none of those families can ever be applied. Scanning
        # it would fail the gate on text that cannot reach a screen; what the gate
        # is for is a real font sneaking into hand-written CSS or a template.
        unreachable_fallback = re.compile(r"var\(--default-font-family,[^)]*\)")
        violations = []
        for path in _production_frontend_files():
            text = unreachable_fallback.sub("", path.read_text(encoding="utf-8"))
            match = forbidden.search(text)
            if match:
                violations.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
        self.assertEqual(
            violations, [], "Unapproved UI fonts: " + ", ".join(violations)
        )

    def test_charts_explicitly_use_geist_sans(self):
        charts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "templates").rglob("*.html")
            if "fontFamily" in path.read_text(encoding="utf-8")
        )
        self.assertNotIn("fontFamily: 'Outfit", charts)
        self.assertNotIn('fontFamily: "Outfit', charts)
        self.assertNotIn("fontFamily: 'Inter", charts)
        self.assertIn("fontFamily: 'Geist Sans", charts)

    def test_content_cards_use_intrinsic_height_while_kpi_grids_stay_aligned(self):
        # Asserted against platform.css only: it is the stylesheet base.html
        # actually loads. This previously also asserted against
        # edify-components.css, which no template ever referenced — a contract
        # pinned to dead code. That file has since been removed along with
        # edify-pages.css and edify-tokens.css (the latter advertised itself as
        # "THE SINGLE SOURCE OF TRUTH" while shipping values that contradicted
        # the live tokens).
        platform = _read("static/css/platform.css")
        content_card_rule = platform.split(
            "Content cards keep their intrinsic height", 1
        )[1].split('main :where([class*="kpi-grid"]', 1)[0]
        self.assertIn("align-self: start", content_card_rule)
        self.assertIn("block-size: auto", content_card_rule)
        self.assertIn("align-items: stretch", platform)
        self.assertIn("block-size: 100%", platform)
        self.assertNotIn("height: 108px", platform)

    def test_special_project_plan_sidebar_owns_its_grid_placement_and_height(self):
        project_plan = _read("static/css/pages/special-project-my-plan.css")

        insights_rule = project_plan.split(".sp-insights {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-column: auto", insights_rule)
        self.assertIn("grid-row: auto", insights_rule)
        self.assertIn("align-content: start", insights_rule)
        self.assertNotRegex(project_plan, r"(?m)^\.sp-card:nth-of-type\(n \+ 2\)")
        self.assertIn(".sp-plan-main > .sp-card:nth-of-type(n + 2)", project_plan)

    def test_analytics_dashboard_groups_cards_by_content_scale(self):
        page = _read("templates/pages/analytics/index.html")
        cards = _read("templates/partials/analytics/kpi_cards.html")
        layout = _read("static/css/pages/analytics-dashboard.css")

        self.assertIn("data-analytics-enterprise", page)
        self.assertIn("css/pages/analytics-dashboard.css", page)
        for band in (
            "analytics-executive-pulse",
            "analytics-row--geography",
            "analytics-row--overview",
            "analytics-row--decision",
            "analytics-impact-band",
            "analytics-row--compact",
            "analytics-evidence-disclosure",
        ):
            self.assertIn(band, cards)

        self.assertLess(
            cards.index("target_by_district.html"),
            cards.index("recommended_insights.html"),
        )
        self.assertIn("items=executive_kpi_items", cards)
        self.assertIn("items=additional_kpi_items", cards)
        self.assertNotIn("lg:col-span-4 space-y-6", cards)
        self.assertIn("container: analytics-dashboard / inline-size", layout)
        self.assertIn("container: analytics-impact / inline-size", layout)
        self.assertIn("align-items: stretch", layout)
        self.assertNotIn("grid-auto-flow: dense", layout)

    def test_cd_cceo_snapshot_and_leaderboard_share_one_balanced_row(self):
        body = _read("templates/partials/analytics/cd/body.html")
        leaderboard = _read("templates/partials/analytics/cd/cceo_leaderboard.html")
        snapshot = _read("templates/partials/analytics/cd/cceo_snapshot.html")

        performance_row = body.split("data-cd-cceo-performance-row", 1)[1].split(
            "CCEO performance row end", 1
        )[0]
        self.assertIn("cceo_snapshot.html", performance_row)
        self.assertIn("cceo_leaderboard.html", performance_row)
        self.assertIn("lg:grid-cols-2", performance_row)
        self.assertIn("items-stretch", performance_row)
        self.assertIn("max-h-[280px]", leaderboard)
        self.assertIn("sticky top-0 edify-surface", leaderboard)
        self.assertIn("min-w-[520px]", snapshot)
        self.assertIn("min-w-[560px]", leaderboard)
        self.assertIn("min-w-0 w-full edify-surface", snapshot)
        self.assertIn("min-w-0 w-full edify-surface", leaderboard)

    def test_shared_responsive_contract_covers_mobile_and_tablet(self):
        platform = _read("static/css/platform.css")
        self.assertIn("@media (max-width: 63.9375rem)", platform)
        self.assertIn("@media (max-width: 47.5rem)", platform)
        self.assertIn("@media (max-width: 30rem)", platform)
        self.assertNotIn("platform-table-cards", platform)
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
        # The @theme block moved out of tailwind.source.css into _theme.css so
        # the sign-in page could get the tokens without the 322 KB application
        # bundle (apps/core/tests/test_login_bundle.py). Still defined ONCE —
        # both tailwind.source.css and tokens.source.css import that one block.
        source = _read("assets/css/_theme.css")
        compiled = _read("static/css/main.css")
        token_bundle = _read("static/css/tokens.css")
        tokens = _read("static/css/design-system.css")

        for declaration in (
            "--radius-surface: 12px",
            "--radius-control: 8px",
            "--radius-overlay: 16px",
        ):
            self.assertIn(
                declaration, source, f"{declaration} missing from the shared @theme"
            )
            self.assertIn(
                declaration, compiled, f"{declaration} missing from compiled main.css"
            )
            self.assertIn(
                declaration,
                token_bundle,
                f"{declaration} missing from tokens.css — sign-in reads the radii "
                "from login.css without using a rounded-* utility, so a non-static "
                "@theme tree-shakes them away and every radius there renders 0.",
            )

        # No second definition anywhere else in the loaded cascade.
        for token in ("--radius-surface", "--radius-control", "--radius-overlay"):
            self.assertNotIn(
                f"{token}:",
                tokens,
                f"{token} must not be redefined in design-system.css — it is "
                "defined once in assets/css/_theme.css.",
            )

    def test_sign_in_layout_is_not_a_design_system_island(self):
        """The sign-in screen must consume the same token layer as the app.

        It previously loaded login.css alone — no tokens, no shared utilities —
        and had drifted to nine bespoke radii (.95rem, .72rem, 1.5rem, .7rem,
        .78rem, .92rem, .75rem, 999px, 50%) on the first screen every user
        sees. That is the "page-specific design language" §1 forbids.

        The token layer arrives as tokens.css rather than main.css now. The
        requirement was never "load the application bundle" — it was "consume
        the canonical tokens instead of inventing values", and tokens.css is
        built from the same assets/css/_theme.css main.css is. Loading the
        whole bundle for five custom properties cost 322 KB on the first screen
        every user sees; see apps/core/tests/test_login_bundle.py.
        """
        layout = _read("templates/layouts/login.html")
        login_css = _read("static/css/login.css")

        self.assertIn("css/tokens.css", layout)
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

    def test_dark_workspace_matches_the_editorial_surface_contract(self):
        tokens = _read("static/css/design-system.css")
        platform = _read("static/css/platform.css")
        consistency = _read("static/css/consistency.css")
        night_tokens = tokens.split(":root.theme-dark {", 1)[1].split("\n}", 1)[0]

        for declaration in (
            "--edify-bg: #0e151c",
            "--edify-section-bg: #111a22",
            "--edify-surface-muted: #121c25",
            "--edify-surface: #151f29",
            "--edify-surface-raised: #1a2732",
            "--edify-surface-hover: #1e2e3a",
            "--edify-border: #31404d",
            "--edify-border-strong: #566d7d",
            "--edify-control-border: var(--edify-border-strong)",
            "--edify-surface-treatment: none",
            "--edify-button-primary-treatment: none",
            "--edify-button-secondary-treatment: none",
            "--edify-card-surface: var(--edify-surface)",
            "--edify-card-border: #2d3d49",
            "--edify-table-header: #1a2833",
            "--edify-table-row-alt: #14212b",
            "--edify-table-row-hover: #1b3446",
            "--edify-card-shadow:",
            "--edify-card-shadow-hover:",
            "--edify-shadow-sm: none",
            "--edify-shadow-md: none",
            "--edify-shadow-lg: none",
            "--edify-shadow-drawer: none",
            "--edify-text: #edf3f7",
            "--edify-text-muted: #bdc9d4",
            "--edify-text-subtle: #8fa0ad",
            "--edify-accent: var(--brand-primary)",
            "--edify-warning: #e7b45a",
        ):
            self.assertIn(declaration, night_tokens)

        self.assertGreaterEqual(_contrast_ratio("#edf3f7", "#0e151c"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#bdc9d4", "#151f29"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#8fa0ad", "#151f29"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#ffffff", "#2f78b7"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#566d7d", "#151f29"), 3.0)
        self.assertIn(
            "DARK WORKSPACE — QUIET NIGHT CANVAS, OPERATIONAL CLARITY", platform
        )
        self.assertIn(
            "background-image: var(--edify-button-primary-treatment)", platform
        )
        self.assertIn("GLOBAL BORDERLESS SURFACE CONTRACT", consistency)
        self.assertIn(".kpi-strip__item", consistency)
        self.assertIn(".settings-detail-tile", consistency)
        self.assertIn(".premium-card-elevated", consistency)
        self.assertIn(":has(> table)", consistency)
        self.assertIn(".shadow-2xl", consistency)
        self.assertIn("background-color: var(--edify-card-surface)", consistency)
        self.assertIn("border-width: 1px", consistency)
        self.assertIn("border-radius: var(--edify-radius-sm)", consistency)
        self.assertIn("border-color: var(--edify-border-strong)", consistency)
        self.assertIn("background-image: none !important", platform)
        self.assertIn("box-shadow: none !important", platform)

    def test_blue_workspace_matches_the_elevated_surface_contract(self):
        tokens = _read("static/css/design-system.css")
        components = _read("static/css/components.css")
        consistency = _read("static/css/consistency.css")
        blue_tokens = tokens.split(":root.theme-blue {", 1)[1].split("\n}", 1)[0]

        for declaration in (
            "--edify-surface: rgba(5, 54, 96, 0.58)",
            "--edify-surface-muted: rgba(5, 54, 96, 0.58)",
            "--edify-surface-raised: rgba(5, 54, 96, 0.58)",
            "--edify-border: rgba(123, 189, 232, 0.32)",
            "--edify-surface-treatment: none",
            "--edify-glass-tile-treatment: none",
            "--edify-glass-kpi-treatment: none",
            "--edify-button-primary-treatment: none",
            "--edify-button-secondary-treatment: none",
            "--edify-glass-blur: 0px",
            "--edify-card-surface: var(--edify-surface)",
            "--edify-card-border: transparent",
            "--edify-card-shadow:",
            "--edify-card-shadow-hover:",
            "--edify-card-backdrop-filter: none",
            "--edify-table-canvas: var(--edify-surface)",
            "--edify-shadow-sm: none",
            "--edify-shadow-md: none",
            "--edify-shadow-lg: none",
            "--edify-shadow-drawer: none",
            "--edify-topbar-shadow: none",
        ):
            self.assertIn(declaration, blue_tokens)

        self.assertIn("GLOBAL BORDERLESS SURFACE CONTRACT", consistency)
        self.assertIn("Blue primary actions stay unmistakable", consistency)
        for surface in (
            ".platform-hero",
            ".hcos-register",
            ".admin-period-switch",
            ".tt-signal-strip",
            ".drawer-surface",
            ".pto-drawer-panel",
            ".tt-modal__panel",
        ):
            self.assertIn(surface, consistency)
        self.assertIn("background-image: none !important", components)
        self.assertIn("backdrop-filter: none", components)

    def test_drawers_use_the_centered_reference_modal_and_form_contract(self):
        base_drawer = _read("templates/components/drawers/base_drawer.html")
        drawers = _read("static/css/drawers.css")
        consistency = _read("static/css/consistency.css")
        base = _read("templates/base.html")

        # The shared shell powers every drawer, so the reference treatment is
        # implemented once rather than copied into individual feature forms.
        self.assertIn('class="drawer-required-note"', base_drawer)
        self.assertIn("REFERENCE-ALIGNED FLOATING WORKSPACE", drawers)
        self.assertIn("container: drawer / inline-size", drawers)
        self.assertIn("@container drawer (min-width: 44rem)", drawers)
        self.assertIn(
            "grid-template-columns: repeat(2, minmax(0, 1fr))", drawers
        )
        self.assertIn(
            'form:not(.cluster-create-form):not([data-drawer-layout="stack"])',
            drawers,
        )
        self.assertIn("max-height: calc(100dvh - 7rem) !important", drawers)
        self.assertIn("scrollbar-gutter: stable", drawers)
        self.assertIn("overscroll-behavior: contain", drawers)
        self.assertIn(":user-invalid", drawers)

        # Blue and dark modes may flatten page cards, but must not erase the
        # modal hierarchy and focus separation of an active workflow.
        self.assertIn(
            ":is(.theme-blue, .theme-dark) .drawer-surface", consistency
        )
        self.assertIn("box-shadow: var(--drawer-shadow) !important", consistency)
        self.assertIn("20260826modal1", base)

    def test_blue_primary_actions_use_white_ink_on_saturated_blue(self):
        components = _read("static/css/components.css")
        consistency = _read("static/css/consistency.css")

        # White on the Blue workspace action token clears AA at normal text
        # sizes. The former sky-400/navy pairing was readable, but visually
        # presented primary CTAs as selected filters with black labels.
        self.assertGreaterEqual(_contrast_ratio("#ffffff", "#1872bd"), 4.5)
        for stylesheet in (components, consistency):
            self.assertNotIn("color: var(--edify-navy-950) !important;", stylesheet)
            self.assertIn("color: var(--edify-on-accent) !important;", stylesheet)
            self.assertIn(
                "background-color: var(--edify-accent) !important;", stylesheet
            )
            self.assertIn(
                "background-color: var(--edify-accent-hover) !important;",
                stylesheet,
            )

    def test_custom_blue_surfaces_keep_inverse_heading_ink(self):
        consistency = _read("static/css/consistency.css")
        self.assertIn(".edify-inverse-surface", consistency)
        self.assertNotIn("main .edify-inverse-surface", consistency)
        self.assertIn(
            ".edify-inverse-surface :is(h1, h2, h3, .edify-page-title, .edify-inverse-heading)",
            consistency,
        )
        self.assertIn("color: var(--edify-on-accent) !important;", consistency)

        agreement = _read("templates/pages/documents/canonical_document.html")
        self.assertIn(
            'id="agreement-response-title" class="edify-inverse-heading',
            agreement,
        )
        self.assertGreaterEqual(agreement.count("edify-inverse-heading"), 3)

        # These custom surfaces use class- or gradient-driven fills rather
        # than a standard bg-blue/bg-slate utility, so the semantic inverse
        # marker is the durable contract that beats the global h2 colour.
        for template, fragment in (
            (
                "templates/pages/documents/canonical_document.html",
                "agreement-decision edify-inverse-surface",
            ),
            (
                "templates/pages/documents/canonical_document.html",
                "agreement-masthead edify-inverse-surface",
            ),
            (
                "templates/pages/dashboards/special_projects.html",
                "edify-inverse-surface bg-[var(--edify-primary-active)]",
            ),
            (
                "templates/partials/core_schools/champion_review_drawer.html",
                "edify-inverse-surface px-6 py-5 bg-[var(--edify-text)]",
            ),
        ):
            self.assertIn(fragment, _read(template), template)

    def test_bespoke_workspaces_use_the_shared_page_canvas(self):
        consistency = _read("static/css/consistency.css")
        self.assertIn("main > .edify-page-canvas", consistency)
        self.assertIn(
            "padding: 1.25rem var(--edify-page-gutter) !important;",
            consistency,
        )

        custom_workspaces = (
            "templates/pages/accounts/budget_amendments.html",
            "templates/pages/analytics/impact.html",
            "templates/pages/calendar/index.html",
            "templates/pages/dashboards/main.html",
            "templates/pages/hr/module_workspace.html",
            "templates/pages/ia/analytics_dashboard.html",
            "templates/pages/leave/personal_time_off.html",
            "templates/pages/partners/index.html",
            "templates/pages/projects/index.html",
            "templates/pages/projects/detail.html",
            "templates/pages/dashboards/special_projects.html",
            "templates/pages/projects/analytics.html",
            "templates/pages/projects/my_plan.html",
            "templates/pages/projects/planning.html",
            "templates/pages/ssa/performance.html",
            "templates/pages/targets/team.html",
        )
        for template in custom_workspaces:
            self.assertIn("edify-page-canvas", _read(template), template)

        # These are purposefully edge-to-edge: the IA review is an evidence
        # workstation and the conversation document is print-oriented.
        for template in (
            "templates/pages/ia/review_workspace.html",
            "templates/pages/hr/conversation_document.html",
        ):
            self.assertNotIn("edify-page-canvas", _read(template), template)

    def test_every_shell_page_has_a_gutter_contract_or_is_full_bleed(self):
        unspaced = set()
        root_pattern = re.compile(
            r"{%\s*block\s+shell_content\s*%}[\s\S]*?"
            r'<(?:div|section|main|article)\b[^>]*class="([^"]*)"'
        )
        for path in (ROOT / "templates" / "pages").rglob("*.html"):
            match = root_pattern.search(path.read_text(encoding="utf-8"))
            if not match:
                continue
            classes = match.group(1).split()
            has_gutter = (
                "edify-page-canvas" in classes
                or "edify-report-workspace" in classes
                or any(
                    class_name.startswith(("p-", "px-", "sm:p-", "sm:px-"))
                    for class_name in classes
                )
            )
            if not has_gutter:
                unspaced.add(path.relative_to(ROOT).as_posix())

        self.assertEqual(
            unspaced,
            {
                "templates/pages/hr/conversation_document.html",
                "templates/pages/ia/review_workspace.html",
            },
            "Every shell page needs the shared gutter; only purpose-built "
            "full-bleed or print workspaces are exempt.",
        )

    def test_card_actions_size_to_content_without_changing_form_buttons(self):
        consistency = _read("static/css/consistency.css")
        self.assertIn("main .edify-card-action", consistency)
        self.assertIn("inline-size: fit-content !important", consistency)
        self.assertIn("max-inline-size: 100%", consistency)

        card_actions = []
        class_attribute = re.compile(r'class="([^"]*\bedify-card-action\b[^"]*)"')
        for path in (ROOT / "templates").rglob("*.html"):
            for classes in class_attribute.findall(path.read_text(encoding="utf-8")):
                card_actions.append((str(path.relative_to(ROOT)), classes))
                self.assertNotIn(
                    "w-full",
                    classes.split(),
                    f"Card action must keep intrinsic width: {path.relative_to(ROOT)}",
                )

        self.assertGreaterEqual(len(card_actions), 8)

    def test_blue_workspace_tables_have_a_complete_visual_hierarchy(self):
        tokens = _read("static/css/design-system.css")
        platform = _read("static/css/platform.css")

        for declaration in (
            "--edify-table-canvas:",
            "--edify-table-header:",
            "--edify-table-row-alt:",
            "--edify-table-row-hover:",
            "--edify-table-row-selected:",
            "--edify-table-divider:",
        ):
            self.assertIn(declaration, tokens)

        self.assertIn("Blue workspace tables", platform)
        self.assertIn(".theme-blue main table thead th", platform)
        self.assertIn("var(--edify-table-header)", platform)
        self.assertIn("tbody tr:nth-child(even)", platform)
        self.assertIn("tbody tr:is(:hover, :focus-within)", platform)
        self.assertIn('[aria-selected="true"]', platform)
        self.assertIn("var(--edify-table-row-selected)", platform)
        self.assertIn("scrollbar-color: var(--edify-scrollbar-thumb)", platform)

    def test_record_grids_follow_the_premium_operational_contract(self):
        tokens = _read("static/css/design-system.css")
        consistency = _read("static/css/consistency.css")

        for declaration in (
            "--edify-table-cell-padding-block: 0.5rem",
            "--edify-table-cell-padding-inline: 0.75rem",
            "--edify-table-header-weight: 600",
            "--edify-table-body-weight: 450",
            "--edify-table-identity-weight: 600",
            "--edify-table-action-size: 2rem",
            "--edify-table-header-divider:",
        ):
            self.assertIn(declaration, tokens)

        self.assertIn("PREMIUM OPERATIONAL TABLE SYSTEM", consistency)
        self.assertIn(".edify-record-table tbody tr:nth-child(even)", consistency)
        self.assertIn("var(--edify-table-canvas", consistency)
        self.assertIn("var(--edify-table-row-hover", consistency)
        self.assertIn("var(--edify-table-row-selected", consistency)
        self.assertIn('[aria-selected="true"]', consistency)
        self.assertIn('th[aria-sort="ascending"]', consistency)
        self.assertIn('th[aria-sort="descending"]', consistency)
        self.assertIn("[data-record-title]", consistency)
        self.assertIn("[data-record-action]", consistency)
        self.assertIn("@media (pointer: coarse)", consistency)

    def test_priority_matrix_uses_theme_safe_table_surfaces(self):
        matrix = _read("static/css/pages/ia-master.css")

        for declaration in (
            "background: var(--edify-table-header",
            "background: var(--edify-table-canvas",
            "background: var(--edify-table-row-hover",
            "border-bottom: 1px solid var(--edify-table-divider",
            "color: var(--edify-text-muted",
        ):
            self.assertIn(declaration, matrix)

        desktop_table = matrix.split(".ia-master-table th", 1)[1].split(
            ".ia-priority-chip", 1
        )[0]
        self.assertNotIn("background: #fff", desktop_table)
        self.assertNotIn("background: #f8fbfe", desktop_table)

    def test_reference_record_grids_expose_table_semantics(self):
        for relative_path in (
            "templates/pages/trainings/index.html",
            "templates/pages/admin/audit_log.html",
            "templates/partials/projects/portfolio_list.html",
        ):
            template = _read(relative_path)
            self.assertIn("<caption", template, relative_path)
            self.assertIn('scope="col"', template, relative_path)
            self.assertIn("edify-record-table", template, relative_path)

    def test_light_workspace_uses_the_approved_edify_reference_treatment(self):
        tokens = _read("static/css/design-system.css")
        platform = _read("static/css/platform.css")
        base = _read("templates/base.html")

        # Spec §5 brand + §6 four-step light surface ladder.
        for declaration in (
            "--brand-primary: #0e5da3",
            "--brand-primary-hover: #0a4d86",
            "--edify-brand-primary: var(--brand-primary)",
            "--edify-brand-primary-hover: var(--brand-primary-hover)",
            "--edify-brand-secondary: #ef564b",
            "--edify-bg: #e3f2fa",
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
        self.assertIn("getPropertyValue('--edify-bg')", base)
        self.assertNotIn("#e3f2fa", base)

    def test_light_workspace_text_hierarchy_meets_high_contrast_standard(self):
        tokens = _read("static/css/design-system.css")
        platform = _read("static/css/platform.css")

        for declaration in (
            "--edify-text: #17232b",
            "--edify-text-muted: #3f515c",
            "--edify-text-subtle: #5a6b75",
            "--edify-text-disabled: #6b7b84",
        ):
            self.assertIn(declaration, tokens)

        # Body-text steps clear AA on the card plane they actually sit on.
        # (#6b7b84 is the disabled step, which WCAG exempts from the minimum.)
        # #5a6b75 is the subtle step. It was #5f707a until the canvas became
        # the tinted #e3f2fa, against which it measured 4.49:1 — under AA by a
        # hundredth, which is still under. This assertion is what caught it.
        for colour in ("#17232b", "#3f515c", "#5a6b75"):
            self.assertGreaterEqual(_contrast_ratio(colour, "#f8fafb"), 4.5)
            self.assertGreaterEqual(_contrast_ratio(colour, "#e3f2fa"), 4.5)

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
            ".spp-empty",
            ".spa-empty",
            ".tt-modal__panel",
            ".theme-blue main :is(",
            ".theme-dark main :is(",
            ".edify-risk-card, .card-alert",
        ):
            self.assertIn(selector, platform)
        self.assertIn(".kpi-strip__item", _read("static/css/components.css"))

    def test_kpi_labels_use_the_shared_strip_hierarchy(self):
        tokens = _read("static/css/design-system.css")
        platform = _read("static/css/platform.css")
        components = _read("static/css/components.css")

        self.assertIn("--edify-kpi-label-weight: 600", tokens)
        self.assertIn("--edify-kpi-label-tracking:", tokens)
        self.assertIn("KPI label typography", platform)
        self.assertIn("text-transform: none !important", platform)
        self.assertIn(".kpi-strip__label {", components)
        self.assertIn("text-transform: uppercase", components)

        for template in (
            "templates/partials/professional_development/body.html",
            "templates/partials/hr/pd_dashboard/body.html",
            "templates/partials/dashboards/pl/body.html",
            "templates/partials/dashboards/cd/body.html",
            "templates/partials/dashboards/hr/body.html",
            "templates/partials/analytics/cd/body.html",
            "templates/partials/analytics/pl/body.html",
            "templates/partials/debriefs/dashboard_body.html",
            "templates/pages/projects/index.html",
        ):
            self.assertIn("components/kpi_strip.html", _read(template), template)

        program_lead_dashboard = _read("templates/partials/dashboards/pl/body.html")
        self.assertNotIn(
            'class="text-[12px] font-semibold tracking-[0.06em] uppercase"',
            program_lead_dashboard,
        )

    def test_cd_district_heatmap_keeps_its_intrinsic_height(self):
        heatmap = _read("templates/partials/analytics/cd/district_heatmap.html")

        self.assertIn('class="edify-surface self-start ', heatmap)

    def test_full_height_surfaces_are_limited_to_viewport_workspaces(self):
        full_height_surface = re.compile(
            r'class="[^"]*\bedify-surface\b[^"]*\bh-full\b[^"]*"'
        )
        allowed = {
            "templates/partials/messages/conversation.html",
            "templates/partials/messages/thread_list.html",
            "templates/partials/my_plan/activity_detail_drawer.html",
        }
        offenders = []

        for path in (ROOT / "templates").rglob("*.html"):
            relative = str(path.relative_to(ROOT))
            if relative in allowed:
                continue
            if full_height_surface.search(path.read_text(encoding="utf-8")):
                offenders.append(relative)

        self.assertEqual(
            offenders,
            [],
            "Full-height content cards create dead space; reserve h-full for "
            f"viewport workspaces and drawers: {offenders}",
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
        # The intelligence row is one column now. It used to split into a
        # narrow SSA matrix beside a wider urgent-schools card, and that narrow
        # column is what forced the matrix down to six of its eight
        # interventions. The risk list owns the row; the matrix sits below it
        # at full width, where all eight columns fit.
        self.assertIn(
            """.pl-intelligence-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);""",
            pages,
        )
        self.assertNotIn("minmax(0, 0.76fr)", pages)
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
        # q is owned by the top-bar search (search-consolidation mandate);
        # the page must not keep a dangling trigger on the removed input,
        # which would match the topbar input globally and double-fire.
        self.assertNotIn('name="q"', planning_page)
        self.assertNotIn("from:input[name='q']", planning_page)
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
            offenders,
            [],
            f"Use the shared shadow scale, not arbitrary values: {offenders}",
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
        """Geist Sans is the single UI font; a page must not smuggle in another
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
                        if (
                            "--edify-font" not in normalized
                            and "geist" not in normalized
                        ):
                            offenders.append(f"{path}:{lineno} -> {value.strip()[:50]}")
        self.assertEqual(
            offenders,
            [],
            f"Use var(--edify-font-sans); Geist Sans is the only approved UI font: {offenders}",
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

        conflicts = {label: tones for label, tones in seen.items() if len(tones) > 1}
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
            definitions,
            0,
            "focus token scan matched nothing -- the guard has gone blind",
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


class ChartLegendRailGuardTest(SimpleTestCase):
    """Bar and line legends remain a single readable horizontal rail."""

    def test_bar_and_line_legends_use_the_shared_horizontal_layout(self):
        css = _read("static/css/platform.css")

        self.assertIn(
            ".apexcharts-bar-series,\n  .apexcharts-line-series",
            css,
            "The shared legend rule must cover both comparison bars and trends.",
        )
        self.assertIn(
            "flex-flow: row nowrap !important;",
            css,
            "Chart legends must read left-to-right instead of stacking series.",
        )
        self.assertIn(
            "justify-content: flex-start !important;",
            css,
            "Every chart legend must begin from the same predictable edge.",
        )
        self.assertIn(
            "overflow-x: auto !important;",
            css,
            "A narrow viewport must scroll a legend rail instead of collapsing "
            "it into a tall stack.",
        )
        self.assertIn(
            ".apexcharts-legend-group {",
            css,
            "Mixed charts group bar and line series separately; both groups "
            "must still share the same horizontal rail.",
        )
        self.assertIn(
            ".apexcharts-legend-series {",
            css,
            "The platform rule must normalize ApexCharts' per-series spacing.",
        )
        self.assertIn(
            "margin: 0 !important;",
            css,
            "ApexCharts' wide inline margins must not force premature wrapping.",
        )
        self.assertIn(
            "white-space: nowrap !important;",
            css,
            "A legend label must remain one compact, scannable item.",
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
                rest = markup[match.start() :]
                close = rest.find("#}")
                if close == -1:
                    continue
                if "\n" in rest[:close]:
                    line = markup[: match.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{line}")
        self.assertEqual(
            offenders,
            [],
            "Django's {# #} comment does not span newlines, so these render as "
            "visible page text. Use {% comment %}...{% endcomment %} for "
            f"multi-line notes: {offenders}",
        )


class SolidControlInkTest(SimpleTestCase):
    """A filled control is a fill plus its ink, and both must be tokens.

    The destructive confirmation button was `background: var(--edify-danger)`
    with `color: #fff`. That reads correctly in the light theme and fails badly
    in the dark ones, where --edify-danger is a light salmon: white on it
    measured 2.44:1, less than half the AA threshold, on the button that
    deletes a school. Measuring the light theme to check the fix then showed
    white on #ef4444 at 3.76:1 — also under AA, just less obviously.

    Hence two tokens: --edify-danger-solid for the fill and
    --edify-danger-on-solid for the ink, per theme. --edify-danger itself is
    unchanged; it is the semantic red for borders, chart series and tints, and
    recolouring all of those to fix a button would be the wrong trade.
    """

    AA_NORMAL_TEXT = 4.5

    def _theme_blocks(self):
        """Each theme's token block, keyed by the selector that opens it."""
        source = _read("static/css/design-system.css")
        blocks = {}
        for match in re.finditer(r"(:root[^{]*)\{([^}]*)\}", source, re.S):
            selector = match.group(1).strip()
            body = match.group(2)
            if "--edify-danger-solid" in body:
                blocks[selector] = body
        return blocks

    @staticmethod
    def _token(body, name):
        match = re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}})", body)
        return match.group(1) if match else None

    def test_every_theme_defines_the_pair(self):
        blocks = self._theme_blocks()
        self.assertGreaterEqual(len(blocks), 3, f"themes found: {list(blocks)}")
        for selector, body in blocks.items():
            with self.subTest(theme=selector):
                self.assertIsNotNone(self._token(body, "--edify-danger-solid"))
                self.assertIsNotNone(self._token(body, "--edify-danger-on-solid"))

    def test_the_destructive_button_is_readable_in_every_theme(self):
        for selector, body in self._theme_blocks().items():
            fill = self._token(body, "--edify-danger-solid")
            ink = self._token(body, "--edify-danger-on-solid")
            with self.subTest(theme=selector, fill=fill, ink=ink):
                ratio = _contrast_ratio(ink, fill)
                self.assertGreaterEqual(
                    ratio,
                    self.AA_NORMAL_TEXT,
                    f"{selector}: {ink} on {fill} is {ratio:.2f}:1",
                )

    def test_no_solid_danger_control_hardcodes_its_ink(self):
        """The whole point of the token is that no component chooses again."""
        components = _read("static/css/components.css")
        offenders = re.findall(
            r"background:\s*var\(--edify-danger[^)]*\);\s*\n\s*color:\s*(#fff|#ffffff|white)\b",
            components,
        )
        self.assertEqual(offenders, [], f"hardcoded ink on a danger fill: {offenders}")


class TypeScaleFloorTest(SimpleTestCase):
    """Six readable tiers, and nothing smaller than the micro tier.

    The stylesheets had 169 sub-12px font-size declarations across eight
    different values — 7, 8, 9, 9.5, 10, 10.5, 11 and 11.5px. That is drift,
    not a scale: the Partner dashboard was styled at 7–9.5px while the token
    layer had already defined the two tiers everyone meant, --edify-text-micro
    for uppercase eyebrows and labels and --edify-text-label for readable
    metadata. Templates had drifted the same way, with nine one-off
    text-[Npx] utilities below the caption token.
    """

    MICRO_PX = 12

    def _source_stylesheets(self):
        # main.css is generated from assets/css/tailwind.source.css and will
        # always contain the literal values its inputs produce.
        return [
            path
            for path in (ROOT / "static" / "css").glob("*.css")
            if path.name != "main.css"
        ]

    def test_no_stylesheet_hardcodes_a_size_below_the_micro_tier(self):
        declaration_pattern = re.compile(r"font-size:\s*([^;}{]+)")
        value_pattern = re.compile(r"(\d*\.?\d+)(px|rem)")
        offenders = []
        for path in self._source_stylesheets():
            for declaration in declaration_pattern.findall(path.read_text()):
                for value, unit in value_pattern.findall(declaration):
                    pixels = float(value) * 16 if unit == "rem" else float(value)
                    if pixels < self.MICRO_PX:
                        offenders.append(f"{path.name}: {value}{unit} ({pixels:g}px)")
        self.assertEqual(offenders, [], f"below the micro tier: {offenders}")

    def test_source_stylesheets_name_every_size_below_the_label_tier(self):
        """Compact text must opt into the micro token, never invent a size."""
        declaration_pattern = re.compile(r"font-size:\s*([^;}{]+)")
        value_pattern = re.compile(r"(\d*\.?\d+)(px|rem)")
        offenders = []
        for path in self._source_stylesheets():
            if path.name == "design-system.css":
                continue
            for declaration in declaration_pattern.findall(path.read_text()):
                for value, unit in value_pattern.findall(declaration):
                    pixels = float(value) * 16 if unit == "rem" else float(value)
                    if pixels < 14:
                        offenders.append(f"{path.name}: {value}{unit} ({pixels:g}px)")
        self.assertEqual(offenders, [], f"unnamed compact text: {offenders}")

    #: The canonical ladder, read straight off the tokens in design-system.css:
    #: micro/floor 12, tile-label 13, label+table 14, body 15, title 16,
    #: card-heading 18, heading 20, tile-value 22, display 28.
    CANONICAL_PX = frozenset({12, 13, 14, 15, 16, 18, 20, 22, 28})

    #: Everything still off the ladder is ABOVE the display tier — hero
    #: numerals at 24, 25, 30, 32, 34, 36, 38, 40, 44 and 48px. The token layer
    #: stops at 28, so there is no rung for them to land on, and collapsing ten
    #: sizes into 28 would visibly resize every hero KPI on the platform. That
    #: is a design decision, not a cleanup, so this holds the line at today's
    #: count until a display tier is defined.
    #:
    #: Lower it when sizes are migrated; never raise it. Was 269 across 94
    #: files before the 2026-08-21 type-scale migration.
    OFF_SCALE_CEILING = 60

    def test_template_type_sizes_stay_on_the_canonical_ladder(self):
        pattern = re.compile(r"text-\[(\d*\.?\d+)px\]")
        offenders = []
        for path in (ROOT / "templates").rglob("*.html"):
            for value in pattern.findall(path.read_text()):
                if float(value) not in self.CANONICAL_PX:
                    offenders.append(f"{path.name}: text-[{value}px]")
        self.assertLessEqual(
            len(offenders),
            self.OFF_SCALE_CEILING,
            f"{len(offenders)} template type sizes sit between the token "
            f"rungs (ceiling {self.OFF_SCALE_CEILING}). Use a canonical size "
            f"or add a token — do not invent a half-step: "
            f"{sorted(set(offenders))[:10]}",
        )

    def test_no_template_uses_a_one_off_tiny_utility(self):
        offenders = []
        pattern = re.compile(r"text-\[(\d{1,2}(?:\.\d)?)px\]")
        for path in (ROOT / "templates").rglob("*.html"):
            for value in pattern.findall(path.read_text()):
                if float(value) < 12:
                    offenders.append(f"{path.name}: text-[{value}px]")
        self.assertEqual(offenders, [], f"tiny text utilities: {offenders}")

    def test_chart_configuration_respects_the_twelve_pixel_floor(self):
        """Chart options cannot bypass the CSS type scale through JavaScript."""
        pattern = re.compile(r"fontSize\s*:\s*['\"](\d+(?:\.\d+)?)px['\"]")
        template_charts = [
            path
            for path in (ROOT / "templates").rglob("*.html")
            if "fontSize" in path.read_text()
        ]
        offenders = []
        for path in [ROOT / "static/js/alpine-components.js", *template_charts]:
            for value in pattern.findall(path.read_text()):
                if float(value) < self.MICRO_PX:
                    offenders.append(f"{path.relative_to(ROOT)}: fontSize {value}px")
        self.assertEqual(offenders, [], f"chart text below the floor: {offenders}")

    def test_table_structure_does_not_use_micro_typography(self):
        """Rows and headers are operational data, not badge-sized metadata."""
        rule_pattern = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
        table_role = re.compile(
            r"table|(?:^|[\s>+~,])(?:thead|tbody|th|td)(?:\b|[:.#\[])"
        )
        compact_metadata = re.compile(
            r"small|caption|footer|badge|status|overline|eyebrow"
        )
        offenders = []
        for path in self._source_stylesheets():
            text = path.read_text(encoding="utf-8")
            for selector, body in rule_pattern.findall(text):
                if not table_role.search(selector):
                    continue
                if compact_metadata.search(selector):
                    continue
                if "font-size: var(--edify-text-micro-size)" in body:
                    offenders.append(
                        f"{path.name}: {' '.join(selector.split())[-100:]}"
                    )
        self.assertEqual(offenders, [], f"micro-sized table structure: {offenders}")

    def test_inline_template_css_respects_the_twelve_pixel_floor(self):
        declaration_pattern = re.compile(r"font-size\s*:\s*([^;}{]+)")
        value_pattern = re.compile(r"(\d*\.?\d+)(px|rem)")
        offenders = []
        for path in (ROOT / "templates").rglob("*.html"):
            for declaration in declaration_pattern.findall(path.read_text()):
                for value, unit in value_pattern.findall(declaration):
                    pixels = float(value) * 16 if unit == "rem" else float(value)
                    if pixels < self.MICRO_PX:
                        offenders.append(f"{path.relative_to(ROOT)}: {value}{unit}")
        self.assertEqual(offenders, [], f"inline text below the floor: {offenders}")

    def test_readable_core_tiers_are_defined(self):
        tokens = _read("static/css/design-system.css")
        self.assertIn("--edify-text-floor:        0.75rem;", tokens)
        self.assertIn("--edify-text-micro-size:   var(--edify-text-floor);", tokens)
        self.assertIn(
            "--edify-text-label-size:   0.8125rem;",
            tokens,
        )
        self.assertIn(
            "--edify-text-body-size:    0.8125rem;",
            tokens,
        )

    def test_legacy_compact_template_utilities_map_to_the_label_tier(self):
        consistency = _read("static/css/consistency.css")
        for utility in (
            ".text-xs",
            '[class*="text-[12px]"]',
            '[class*="text-[12.5px]"]',
            '[class*="text-[13px]"]',
        ):
            self.assertIn(utility, consistency)
        self.assertIn(
            "font-size: var(--edify-text-label-size) !important;",
            consistency,
        )


class StableTypographyContractTest(SimpleTestCase):
    """Typography stays stable while component layout responds around it."""

    def test_core_and_component_type_steps_do_not_continuously_resize(self):
        tokens = _read("static/css/design-system.css")
        components = _read("static/css/components.css")
        consistency = _read("static/css/consistency.css")

        typography_block = tokens.split("/* ── TYPOGRAPHY SCALE", 1)[1].split(
            "/* ── SPACING", 1
        )[0]
        self.assertNotRegex(typography_block, r"\b(?:clamp|calc)\(")
        self.assertNotRegex(typography_block, r"\b(?:vw|cqi|cqw)\b")

        # Containers still respond by changing layout, never the type scale.
        # (The edify-kpi-card twin left with the legacy adapter — the classes
        # it served have no template usage and the old design is deleted.)
        self.assertIn("container: kpi-card / inline-size", components)
        self.assertIn("@container kpi-card (max-width: 16rem)", components)
        self.assertIn("font-size: var(--edify-text-tile-value-size)", components)

    def test_responsive_svg_text_uses_screen_stable_typography(self):
        """A viewBox must not scale the app's semantic font sizes."""
        offenders = []
        svg_pattern = re.compile(r"<svg\b(?P<attrs>[^>]*)>(?P<body>.*?)</svg>", re.S)
        for path in (ROOT / "templates").rglob("*.html"):
            for match in svg_pattern.finditer(path.read_text(encoding="utf-8")):
                if "<text" not in match.group("body"):
                    continue
                if "data-edify-svg-typography" not in match.group("attrs"):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(
            offenders, [], f"responsive SVG text without sizing: {offenders}"
        )

        # The regional map creates its text nodes in JavaScript, so it cannot
        # be discovered by the literal <text> scan above.
        map_template = _read("templates/partials/analytics/regional_performance.html")
        self.assertIn("data-edify-svg-typography", map_template)

    def test_svg_typography_runtime_uses_tokens_and_tracks_layout_changes(self):
        base = _read("templates/base.html")
        runtime = _read("static/js/svg-typography.js")

        self.assertIn("js/svg-typography.js", base)
        self.assertIn("ResizeObserver", runtime)
        self.assertIn("htmx:afterSwap", runtime)
        self.assertIn("svg.viewBox.baseVal", runtime)
        self.assertIn("rect.width / viewBox.width", runtime)
        self.assertIn("`${size / scale}px`", runtime)
        self.assertIn("20260804svgtype2", base)
        for token in (
            "--edify-text-micro-size",
            "--edify-text-label-size",
            "--edify-text-body-size",
            "--edify-text-title-size",
        ):
            self.assertIn(token, runtime)
        self.assertIn("`--edify-svg-text-${tier}`", runtime)

    def test_compact_scale_has_small_caps_without_sub_twelve_pixel_text(self):
        tokens = _read("static/css/design-system.css")

        for expected in (
            "--edify-text-display-size: 1.25rem;",
            "--edify-text-heading-size: 1rem;",
            "--edify-text-tile-value-size: 1.25rem;",
            "--edify-text-table-size: 0.8125rem;",
            "--edify-text-floor:        0.75rem;",
            "--edify-text-micro-size:   var(--edify-text-floor);",
        ):
            self.assertIn(expected, tokens)
        # Headers sit one step below cells (12px medium, muted) per the
        # reference dashboard — the band separates by weight and colour.
        self.assertIn(
            "--edify-text-table-heading-size: 0.75rem;",
            tokens,
        )

    def test_metric_labels_yield_columns_instead_of_wrapping(self):
        components = _read("static/css/components.css")
        consistency = _read("static/css/consistency.css")
        pages = _read("static/css/pages.css")
        hcos = _read("static/css/hcos-workspace.css")

        self.assertIn("minmax(min(100%, 14rem), 1fr)", components)
        self.assertIn(
            "grid-template-columns: repeat(2, minmax(0, 1fr)) !important",
            components,
        )
        self.assertRegex(
            components,
            r"\.kpi-strip__label\s*\{[^}]*text-wrap:\s*nowrap;"
            r"[^}]*white-space:\s*nowrap;",
        )
        self.assertIn("container: metric-tile / inline-size", components)
        self.assertIn("container: metric-tile / inline-size", pages)
        self.assertIn("container: metric-tile / inline-size", hcos)
        self.assertIn(".settings-detail-tile__label {", components)
        self.assertIn(".pto-balance-tile__top > span:first-child {", pages)
        self.assertIn(".hcos-metric span:not(.hcos-metric__marker)", hcos)

    def test_tables_scroll_before_headers_or_words_are_crushed(self):
        platform = _read("static/css/platform.css")

        self.assertIn("--edify-text-table-size", _read("static/css/design-system.css"))
        self.assertIn("container: edify-table / inline-size", platform)
        self.assertIn("font-size: var(--edify-text-table-size) !important", platform)
        self.assertIn(".drawer-body table th {", platform)
        self.assertIn(".drawer-body table td {", platform)
        self.assertIn(
            "--edify-text-table-heading-size: 0.75rem;",
            _read("static/css/design-system.css"),
        )
        self.assertIn("text-wrap: nowrap", platform)
        self.assertIn("white-space: nowrap", platform)
        self.assertIn("overflow-x: auto", platform)
        self.assertIn("word-break: normal", platform)

        # The all-screen no-wrap contract must reach drawer and dialog tables,
        # not only main — a drawer table wrapping while the page behind it
        # does not reads as two different products. This selector was
        # main-only when first written.
        consistency = _read("static/css/consistency.css")
        self.assertIn(
            ':is(main, .drawer-surface, .edify-popup-dialog__surface, [role="dialog"])',
            consistency,
        )
        self.assertIn(
            "table:not(.sr-only, .edify-visually-hidden) :is(td, th)",
            consistency,
        )
        self.assertIn("EVERY TABLE STAYS ON ONE LINE", consistency)
        self.assertIn("white-space: nowrap !important", consistency)


class TemplateFilterArgumentGuardTest(SimpleTestCase):
    """A dotted fallback in a filter ARGUMENT is a latent 500.

    Django protects the variable but not the argument. In
    FilterExpression.resolve the variable is wrapped in try/except
    VariableDoesNotExist and falls back to string_if_invalid; the argument is
    resolved with a bare `arg.resolve(context)` and nothing catches it. So

        {{ school.sub_county.name|default:school.district.name }}

    fails soft on the left and raises on the right — the fallback, which exists
    precisely for the case where data is missing, is the thing that breaks when
    data is missing. That 500'd the Add to Cluster drawer for every school in
    production, because every school had a null district.

    {% firstof %} resolves each candidate with ignore_failures and skips the
    ones that are absent, which is the behaviour the default filter is being
    reached for in the first place.
    """

    # `|default:"—"` and `|default:'Search'` are literals, not lookups, and
    # cannot raise. Only a dotted path can.
    DOTTED_ARGUMENT = re.compile(
        r"\|\s*default(?:_if_none)?:\s*[A-Za-z_][\w]*(?:\.[\w]+)+"
    )

    def test_no_template_uses_a_dotted_default_argument(self):
        offenders = []
        for path in sorted((ROOT / "templates").rglob("*.html")):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if self.DOTTED_ARGUMENT.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(
            offenders,
            [],
            "A dotted fallback in a filter argument raises VariableDoesNotExist "
            "rather than falling back. Use {% firstof a b %} instead: "
            + ", ".join(offenders),
        )

    def test_the_guard_would_actually_catch_one(self):
        """The pattern above is easy to write so it matches nothing at all."""
        self.assertTrue(
            self.DOTTED_ARGUMENT.search(
                "{{ school.sub_county.name|default:school.district.name }}"
            )
        )
        self.assertTrue(self.DOTTED_ARGUMENT.search("{{ a|default_if_none:b.c }}"))
        # Literals must not be flagged — they cannot fail to resolve.
        self.assertIsNone(self.DOTTED_ARGUMENT.search('{{ a|default:"—" }}'))
        self.assertIsNone(self.DOTTED_ARGUMENT.search("{{ a|default:'Search' }}"))
        self.assertIsNone(self.DOTTED_ARGUMENT.search("{{ a|default:b }}"))


class TableColumnBudgetTest(SimpleTestCase):
    """No table content is folded or truncated to satisfy a viewport."""

    def test_cells_keep_full_single_line_content_at_every_breakpoint(self):
        consistency = _read("static/css/consistency.css")

        self.assertIn("inline-size: max-content", consistency)
        self.assertIn("max-inline-size: none !important", consistency)
        self.assertIn("overflow: visible !important", consistency)
        self.assertIn("text-overflow: clip !important", consistency)
        self.assertIn("white-space: nowrap !important", consistency)
