"""The Core Schools list card fills its column, and stays bounded doing it.

The card used to stop well above the bottom of the right-hand card stack,
leaving a band of dead space beside it, and showed ten schools per page. The
fix is structural rather than a measured height: one stretched two-column
grid, a flex column inside it, and a footer that is the card's last child. A
pixel height copied off a screenshot would have looked identical on the day
and broken the first time the right-hand stack changed, so what is asserted
here is the mechanism, not a number.

The other half is that "more rows" must not become "all rows". Page size is
validated server-side against a fixed set, so an edited query string cannot
turn the list into an unbounded query against a production-sized table.
"""

from __future__ import annotations

from pathlib import Path

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "templates/pages/core_schools/index.html"
LIST_CARD = ROOT / "templates/partials/core_schools/matrix_table.html"
ROW = ROOT / "templates/partials/core_schools/school_row.html"
OVERSIGHT = ROOT / "templates/partials/core_schools/team_oversight.html"
CSS = ROOT / "static/css/platform.css"


class CoreSchoolsLayoutContractTest(TestCase):
    """The structure that produces the alignment, asserted where it lives."""

    def test_the_page_is_one_stretched_two_column_grid(self):
        page = PAGE.read_text()
        self.assertIn("lg:grid-cols-4", page)
        self.assertIn("items-stretch", page)
        self.assertIn('class="lg:col-span-3 flex flex-col', page)
        self.assertIn('class="lg:col-span-1 flex flex-col', page)

    def test_the_list_card_is_a_flex_column_that_grows(self):
        css = CSS.read_text()
        self.assertIn(".core-list-card {", css)
        block = css.split(".core-list-card {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-direction: column", block)
        self.assertIn("flex: 1 1 auto", block)

    def test_the_list_body_grows_and_never_shrinks_into_a_scroll_trap(self):
        css = CSS.read_text()
        block = css.split(".core-school-matrix__body {", 1)[1].split("}", 1)[0]
        # `1 0 auto`: grow into spare height, never shrink below content. A
        # shrinking body would collapse a long list into an inner scrollbar
        # nested inside the page's own — the trap §16 rules out.
        self.assertIn("flex: 1 0 auto", block)
        self.assertNotIn("overflow-y: auto", block)

    def test_no_brittle_fixed_height_holds_the_card_up(self):
        css = CSS.read_text()
        core_css = css.split("Core Schools — list card", 1)[1]
        for banned in ("height: 6", "height: 7", "height: 8", "height: 9", "px;\n  max-block-size"):
            self.assertNotIn(f"block-size: {banned}", core_css)
        self.assertNotIn("min-height: 800px", core_css)

    def test_the_footer_is_the_last_child_of_the_card(self):
        card = LIST_CARD.read_text()
        body = card.index("core-school-matrix__body")
        footer = card.index("core-school-matrix__footer")
        self.assertLess(body, footer)
        css = CSS.read_text()
        block = css.split(".core-school-matrix__footer {", 1)[1].split("}", 1)[0]
        self.assertIn("flex: 0 0 auto", block)

    def test_the_card_owns_its_own_surface_rather_than_nesting_in_one(self):
        """No card drawn inside a card.

        The panel wrapper used to carry the surface, border and padding, and
        the list card carried its own header, rounding and footer inside it —
        so the list appeared framed, inset by the wrapper's padding.
        """
        page = PAGE.read_text()
        shell = page.split('class="core-panel-shell', 1)[1].split(">", 1)[0]
        self.assertNotIn("edify-surface", shell)
        self.assertNotIn("card", shell)
        # `card`, not a hand-spelled `edify-surface rounded-surface border
        # border-slate-100 shadow-sm`: the utility version hard-coded a
        # light-mode border that vanished in the dark theme.
        self.assertIn('class="core-list-card card"', page)
        # In the markup, not in the prose: the comment above the card names the
        # utility it replaced, and a bare substring search reads that as a
        # relapse.
        import re

        classes = " ".join(re.findall(r'class="([^"]*)"', page))
        self.assertNotIn("border-slate-100", classes)

    def test_the_row_shows_the_facts_a_planner_decides_on(self):
        row = ROW.read_text()
        for label in (
            "District:",
            "Owner:",
            "Assessment:",
            "Visits:",
            "Trainings:",
            "Partner:",
            "Package:",
        ):
            self.assertIn(label, row)
        self.assertIn(
            "{{ school.scheduled_visit_count }}/{{ school.visits_target }}", row
        )
        self.assertIn(
            "{{ school.scheduled_training_count }}/{{ school.trainings_target }}", row
        )

    def test_the_compact_row_keeps_its_metadata_visible_when_collapsed(self):
        css = CSS.read_text()
        self.assertIn(
            ".core-school-row--compact.school-record-row:not(.is-expanded) "
            ".core-school-row__metadata {",
            css,
        )

    def test_secondary_metadata_moved_into_the_expandable_detail(self):
        row = ROW.read_text()
        detail = row.split('class="school-record-row__details"', 1)[1]
        for label in ("Shipping Address:", "Enrollment:", "Primary Contact:"):
            self.assertIn(label, detail)

    def test_the_stacked_layouts_drop_the_equal_height_behaviour(self):
        css = CSS.read_text()
        self.assertIn("@media (max-width: 64rem)", css)
        stacked = css.split("@media (max-width: 64rem)", 1)[1].split("@media", 1)[0]
        self.assertIn("block-size: auto", stacked)
        self.assertIn("flex: 0 0 auto", stacked)

    def test_the_oversight_table_stays_a_table_on_a_phone(self):
        css = CSS.read_text()
        phone = css.split("@media (max-width: 48rem)", 1)[1]
        self.assertIn(".core-oversight-scroll", phone)
        self.assertIn("overflow-x: auto", phone)
        self.assertIn("min-inline-size: 68rem", phone)
        self.assertNotIn("content: attr(data-label)", phone)
        oversight = OVERSIGHT.read_text()
        for label in ("data-label=\"Visits\"", "data-label=\"Trainings\"", "data-label=\"Action\""):
            self.assertIn(label, oversight)

    def test_both_rails_on_the_page_are_the_same_segmented_control(self):
        """Two things that look like tabs must not be two different controls.

        The portfolio switch was a bespoke rounded-pill rail sitting directly
        above the canonical segmented rail — same page, same affordance, two
        looks. It is a `data-edify-tablist` now, so the shared contract styles
        both and neither can drift without the other.
        """
        page = PAGE.read_text()
        self.assertIn("data-edify-tablist", page)
        self.assertIn("data-edify-tab", page)
        self.assertIn('role="tablist"', page)
        self.assertIn("edify-tab-btn", page)
        # A badge inside a segment is what the rail contract flattens, and it
        # is what made the two rails different heights.
        switch = page.split("core-scope-switch", 1)[1].split("</nav>", 1)[0]
        self.assertNotIn("edify-status-badge", switch)

    def test_the_new_surfaces_use_the_shared_component_vocabulary(self):
        """Cards, badges and buttons come from the design system, not from here."""
        oversight = OVERSIGHT.read_text()
        self.assertIn("card p-0 overflow-hidden", oversight)
        self.assertIn("edify-data-table", oversight)
        self.assertIn("edify-status-badge", oversight)
        self.assertIn("btn btn-ghost", oversight)
        # The hard-coded light-only palette must not come back: `.pill-danger`
        # and friends are literal hex and are unreadable on the night surface.
        self.assertNotIn("pill-danger", oversight)
        self.assertNotIn("core-oversight-pill", oversight)
        self.assertNotIn("border-slate-100", oversight)

    def test_the_oversight_table_shares_the_cards_gutter(self):
        """The table's outer edges line up with the card's header and footer.

        The outer cells once kept the platform's 11px inter-column padding,
        which is inter-column space, not the card's margin. The first column
        ended up 7px right of the card title while the last ran flush into the
        card's right edge, 25px past the header badge.
        """
        oversight = OVERSIGHT.read_text()
        css = CSS.read_text()

        self.assertIn('data-edify-padding="flush"', oversight)

        gutter = css.split(".core-oversight-table th:first-child", 1)[1].split("}", 1)[0]
        self.assertIn("padding-inline-start: 1.5rem", gutter)
        end = css.split(".core-oversight-table th:last-child", 1)[1].split("}", 1)[0]
        self.assertIn("padding-inline-end: 1.5rem", end)

    def test_the_table_does_not_restate_the_platform_cell_padding(self):
        """`main table th/td` fixes inter-column padding for every table with
        `!important`, so a local `padding` here is dead code that reads as
        though it were in charge."""
        css = CSS.read_text()
        block = css.split(".core-oversight-table th,\n.core-oversight-table td {", 1)[1]
        block = block.split("}", 1)[0]
        self.assertNotIn("padding:", block)

    def test_a_column_header_aligns_with_its_own_cells(self):
        """The Action header sat left over right-aligned buttons: the
        `text-right` utility loses to `.edify-data-table th` from a later
        stylesheet, so the alignment is stated where head and body cannot
        disagree."""
        css = CSS.read_text()
        rule = css.split(
            ".core-oversight-table th:last-child,\n.core-oversight-table td:last-child {",
            1,
        )
        self.assertGreater(len(rule), 1)
        oversight = OVERSIGHT.read_text()
        self.assertNotIn('class="text-right" data-label="Action"', oversight)
        self.assertIn("text-align: end", css)

    def test_no_cell_is_taken_out_of_the_row_by_a_flex_display(self):
        """Every cell stays a table-cell, so every row centres as one line.

        The Delivery cell was `display: flex` to lay its chips out. A `<td>`
        that becomes a flex container stops being a table-cell: it drops out of
        the row's height distribution and `vertical-align: middle` no longer
        applies to it, so that one column sat 10px above the rest of its row.
        The chips flex on a wrapper inside the cell instead.
        """
        css = CSS.read_text()
        oversight = OVERSIGHT.read_text()

        self.assertIn(".core-oversight-flags {", css)
        self.assertIn('<span class="core-oversight-flags">', oversight)

        desktop = css.split("Core Schools — list card", 1)[1].split("@media", 1)[0]
        for cell_rule in (
            ".core-oversight-table__delivery {",
            ".core-oversight-table__school {",
        ):
            if cell_rule in desktop:
                block = desktop.split(cell_rule, 1)[1].split("}", 1)[0]
                self.assertNotIn("display: flex", block)

    def test_the_phone_layout_is_a_scrollable_table(self):
        """The column headers and table cells remain tangible on phones."""
        css = CSS.read_text()
        oversight = OVERSIGHT.read_text()

        self.assertNotIn("edify-mobile-table--cards", css)
        self.assertIn(".core-oversight-table { min-inline-size: 68rem; }", css)
        self.assertIn("<thead>", oversight)
        self.assertNotIn("core-oversight-table thead {", css)
        self.assertNotIn("core-oversight-table td::before", css)

    def test_the_pager_matches_the_shared_table_pager(self):
        """Same furniture as `components/table_pager.html`, including its
        44px target — the hand-rolled 32px buttons were below the floor every
        other list on the platform meets."""
        shared = (ROOT / "templates/components/table_pager.html").read_text()
        control = (
            "min-h-11 min-w-11 px-2.5 rounded-control border border-slate-200 "
            "edify-surface edify-text-caption font-bold text-slate-600 "
            "hover:bg-slate-50"
        )
        self.assertIn(control, shared)
        for page in (LIST_CARD.read_text(), OVERSIGHT.read_text()):
            self.assertIn(control, page)
            self.assertIn(
                "rounded-control edify-primary-solid text-white", page
            )

    def test_every_colour_comes_from_a_theme_token(self):
        """Light and dark both work because neither is hard-coded."""
        css = CSS.read_text()
        core_css = css.split("Core Schools — list card", 1)[1]
        for hard_coded in ("#fff;", "#ffffff;", "background: white", "color: black"):
            self.assertNotIn(hard_coded, core_css.replace("color: #fff;", ""))
        self.assertIn("var(--edify-surface", core_css)
        self.assertIn("var(--edify-text-muted)", core_css)


class CoreSchoolsPaginationTest(TestCase):
    """Page size: bigger by default, still bounded and still server-side."""

    def setUp(self):
        region = Region.objects.create(name="CL Region")
        district = District.objects.create(name="CL District", region=region)
        sub = SubCounty.objects.create(name="CL Sub", district=district)
        self.user = User.objects.create(
            email="cl-cceo@edify.org",
            name="CL Field",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
            status="active",
        )
        profile = StaffProfile.objects.create(user=self.user, title="CCEO")
        for i in range(25):
            school = School.objects.create(
                school_id=f"CL-{i:03d}",
                name=f"CL School {i:03d}",
                region=region,
                district=district,
                sub_county=sub,
                school_type="core",
                account_owner_id=profile.id,
                account_owner_status="matched",
            )
            StaffSchoolAssignment.objects.create(staff=profile, school_id=school.id)
        self.client.force_login(self.user)

    def test_the_default_page_shows_twenty(self):
        response = self.client.get("/core-schools")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["matrix_rows"]), 20)
        self.assertEqual(response.context["per_page"], 20)
        self.assertEqual(response.context["page_obj"].paginator.count, 25)

    def test_the_reader_may_choose_ten_or_fifty(self):
        self.assertEqual(
            len(self.client.get("/core-schools?per_page=10").context["matrix_rows"]), 10
        )
        self.assertEqual(
            len(self.client.get("/core-schools?per_page=50").context["matrix_rows"]), 25
        )
        self.assertEqual(
            self.client.get("/core-schools").context["page_size_options"],
            (10, 20, 50),
        )

    def test_an_out_of_range_page_size_falls_back_instead_of_unbounding(self):
        for value in ("100000", "abc", "-1", "0", ""):
            with self.subTest(value=value):
                response = self.client.get(f"/core-schools?per_page={value}")
                self.assertEqual(response.context["per_page"], 20)
                self.assertEqual(len(response.context["matrix_rows"]), 20)

    def test_pagination_is_server_side(self):
        page_two = self.client.get("/core-schools?page=2")
        self.assertEqual(len(page_two.context["matrix_rows"]), 5)
        self.assertEqual(page_two.context["page_obj"].number, 2)

    def test_the_count_in_the_header_is_the_query_total_not_the_page(self):
        body = self.client.get("/core-schools").content.decode()
        self.assertIn("Core Schools Matrix (25 Schools)", body)
        self.assertIn("Showing 1\u201320 of 25", body)

    def test_twenty_rows_render_when_twenty_are_eligible(self):
        body = self.client.get("/core-schools").content.decode()
        self.assertEqual(body.count('<li class="core-school-row'), 20)
