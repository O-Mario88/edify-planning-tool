"""Platform-wide page hero surface contract."""

import re
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "static" / "css" / "consistency.css"
COMPONENTS = ROOT / "static" / "css" / "components.css"

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

# A page title that is deliberately not a page header. Each of these is a real
# exception, not a page waiting to be migrated:
HEADERLESS_H1_TEMPLATES = {
    # The sign-in split panel: the h1 names the product on a marketing panel,
    # not a page inside the app shell.
    "templates/layouts/auth.html": "auth brand panel, not a page header",
    "templates/pages/auth/login.html": "auth card heading",
    "templates/pages/auth/mfa_verify.html": "auth card heading",
    # A shareable document rendered for people outside the app; it carries the
    # document's own masthead, not the platform's page chrome.
    "templates/pages/documents/canonical_document.html": "public document masthead",
    # A visually hidden heading that exists only to give the review workspace a
    # level-1 outline entry; the visible chrome is a 48px toolbar.
    "templates/pages/ia/review_workspace.html": "sr-only outline heading",
    # The component and the back-link's usage example.
    "templates/components/page_header.html": "the canonical component itself",
    "templates/partials/_back_link.html": "usage example inside a comment",
    # Standalone documents: a redirect interstitial and two print/export views.
    # None of them load the app stylesheet bundle, so a page-header class would
    # style nothing; they carry their own inline print rules instead.
    "templates/pages/auth/launch.html": "redirect interstitial, own document",
    "templates/pages/help/manual_export.html": "print export, own document",
    "templates/pages/help/print_article.html": "print export, own document",
}

TAG = re.compile(
    r"<(/?)([a-zA-Z][\w:-]*)((?:[^<>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>", re.S
)
VOID = {
    "area",
    "base",
    "br",
    "circle",
    "col",
    "ellipse",
    "embed",
    "hr",
    "img",
    "input",
    "line",
    "link",
    "meta",
    "param",
    "path",
    "polygon",
    "polyline",
    "rect",
    "source",
    "stop",
    "track",
    "use",
    "wbr",
}


def _ancestor_classes(source: str, position: int) -> str:
    """Every class on the open elements enclosing `position`."""
    stack: list[tuple[str, str]] = []
    for match in TAG.finditer(source):
        if match.start() >= position:
            break
        closing, name, attrs, self_closing = (
            bool(match.group(1)),
            match.group(2).lower(),
            match.group(3),
            bool(match.group(4)),
        )
        if name in VOID or self_closing:
            continue
        if closing:
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0] == name:
                    del stack[index:]
                    break
        else:
            classes = re.search(r'class\s*=\s*"([^"]*)"', attrs)
            stack.append((name, classes.group(1) if classes else ""))
    return " ".join(classes for _, classes in stack)


class PageHeaderAnatomyContractTest(SimpleTestCase):
    """Every page title sits in a shared header, and every header is one row.

    The surface tests below prove the band looks the same everywhere. These
    prove it is actually *reached* — a page whose title sits in a bare
    `<div class="flex justify-between">` gets no band at all, which is how a
    hundred pages drifted away from the Program Lead Dashboard while the CSS
    that was supposed to unify them looked correct.
    """

    def test_every_page_title_sits_inside_a_shared_header(self):
        families = tuple(selector.lstrip(".") for selector in NAMED_HERO_FAMILIES)
        offenders = []

        for path in sorted(ROOT.glob("templates/**/*.html")):
            relative = path.relative_to(ROOT).as_posix()
            if relative in HEADERLESS_H1_TEMPLATES:
                continue
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(r"<h1[\s>]", source):
                ancestors = " " + _ancestor_classes(source, match.start()) + " "
                if not any(f" {family} " in ancestors for family in families):
                    line = source[: match.start()].count("\n") + 1
                    offenders.append(f"{relative}:{line}")

        self.assertEqual(
            offenders,
            [],
            "these page titles are not inside a shared page header — give the "
            "wrapper `edify-page-header` (see templates/components/"
            "page_header.html) or add a reason to HEADERLESS_H1_TEMPLATES",
        )

    def test_the_header_content_aligns_with_the_rest_of_the_page(self):
        """The band bleeds outward by its own padding.

        Without it the header is the one block on a page whose text is inset by
        the band's padding, and it reads as an accidental indent next to the
        breadcrumb above it and the cards below it.
        """
        for stylesheet in (COMPONENTS, BRIDGE):
            css = stylesheet.read_text(encoding="utf-8")
            with self.subTest(stylesheet=stylesheet.name):
                self.assertIn(
                    "margin-inline: calc(-1 * (var(--page-header-padding-x",
                    css,
                )

    def test_the_lead_has_a_flex_basis_so_controls_stay_on_the_title_row(self):
        """flex-wrap breaks lines on the base size, not the shrunk size.

        A lead left at its max-content width therefore pushes the page's
        filters and buttons onto a second row however much it could have
        shrunk — a different header height on every page.
        """
        for stylesheet in (COMPONENTS, BRIDGE):
            css = stylesheet.read_text(encoding="utf-8")
            with self.subTest(stylesheet=stylesheet.name):
                self.assertIn("flex: 1 1 var(--page-header-lead-basis, 20rem)", css)

    def test_column_direction_headers_release_the_main_axis_basis(self):
        """In a column the shared basis is a height, not a width.

        Every family that flips to column at its own breakpoint has to hand the
        basis back, or its title block becomes a 320px-tall empty band.
        """
        rule_pattern = re.compile(
            r"([^{};]*)\{([^{}]*flex-direction:\s*column[^{}]*)\}", re.S
        )
        column_rules = []
        for path in sorted(ROOT.glob("static/css/**/*.css")):
            if path.name == "main.css":  # generated bundle
                continue
            for rule in rule_pattern.finditer(path.read_text(encoding="utf-8")):
                selector, body = rule.group(1), rule.group(2)
                # Whole class tokens: `.ia-hero__actions` is a child of a
                # header, not a header, and it may legitimately be a column.
                names = set(re.findall(r"\.([\w-]+)", selector))
                if names & {family.lstrip(".") for family in NAMED_HERO_FAMILIES}:
                    column_rules.append((f"{path.name}: {selector.strip()}", body))

        self.assertTrue(column_rules, "expected page-header column rules to exist")
        for where, body in column_rules:
            normalised = body.replace(": ", ":")
            with self.subTest(rule=where):
                self.assertIn("--page-header-lead-basis:auto", normalised)
                self.assertIn("--page-header-align:flex-start", normalised)

    def test_the_eyebrow_keeps_its_own_type_inside_a_header(self):
        """`.edify-page-header p` outranks `.edify-page-eyebrow`.

        One class plus a type beats one class, so without the exclusion every
        eyebrow in the platform rendered as body copy.
        """
        css = COMPONENTS.read_text(encoding="utf-8")
        self.assertIn(".edify-page-header p:not(.edify-page-eyebrow)", css)


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
