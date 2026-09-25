from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
INTERACTIVE_GUARD = "a, button, input, label, select, textarea, [role=button]"


class DirectoryRowInteractionContractTests(SimpleTestCase):
    def test_school_row_empty_space_toggles_without_hijacking_controls(self):
        row = (ROOT / "templates/partials/schools/directory_row.html").read_text()

        self.assertIn("data-row-disclosure-summary", row)
        self.assertIn(f"closest('{INTERACTIVE_GUARD}')", row)
        self.assertIn("openSchoolId = openSchoolId === '{{ school.id }}' ? null", row)
        self.assertIn("frontend:school_detail", row)
        self.assertEqual(row.count("frontend:school_detail"), 1)

    def test_cluster_row_empty_space_toggles_without_hijacking_profile_link(self):
        card = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()

        self.assertIn("data-row-disclosure-summary", card)
        self.assertIn(f"closest('{INTERACTIVE_GUARD}')", card)
        self.assertIn("cardExpanded = !cardExpanded", card)
        # The name is the toggle (ffa2431); the one profile link lives in the
        # expanded details, outside the summary whose empty space toggles.
        summary, details = card.split("<!-- Expanded details block -->", 1)
        self.assertIn('class="cluster-card__name-toggle"', summary)
        self.assertNotIn('href="/clusters/{{ cluster.id }}"', summary)
        self.assertIn('href="/clusters/{{ cluster.id }}"', details)
        self.assertEqual(card.count('href="/clusters/{{ cluster.id }}"'), 1)
        # Since ffa2431 the name is the disclosure button and the profile link
        # opens the details panel, outside the summary's empty-space toggle,
        # so a click on the link can never be taken as a toggle.
        summary, details = card.split("<!-- Expanded details block -->", 1)
        self.assertNotIn('href="/clusters/{{ cluster.id }}"', summary)
        self.assertIn('<a href="/clusters/{{ cluster.id }}"', details)

    def test_cluster_summary_keeps_details_visible_before_expansion(self):
        card = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()

        summary = card.split('class="cluster-card__summary"', 1)[1].split(
            "<!-- Expanded details block -->", 1
        )[0]
        self.assertIn("school-record-row__metadata cluster-card__metadata", summary)
        self.assertIn("Cluster Leader:", summary)
        self.assertIn("SSA Coverage:", summary)

    def test_cluster_expansion_uses_the_shared_ssa_detail_format(self):
        card = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()

        expanded = card.split("<!-- Expanded details block -->", 1)[1]
        self.assertIn("x-transition.opacity.duration.150ms", expanded)
        self.assertIn("partials/schools/ssa_score_groups.html", expanded)
        self.assertIn("selected_fy=selected_fy", expanded)
        self.assertLess(
            expanded.index("partials/schools/ssa_score_groups.html"),
            expanded.index("expanded-schools-"),
        )

    def test_cluster_disclosure_has_keyboard_accessible_native_button(self):
        card = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()

        self.assertIn(':aria-expanded="cardExpanded.toString()"', card)
        self.assertIn('aria-controls="cluster-details-{{ cluster.id }}"', card)
        self.assertIn('id="cluster-details-{{ cluster.id }}"', card)


class PlatformAccordionContractTests(SimpleTestCase):
    """Every accordion starts closed, opens on its row, and holds one item
    open at a time (owner, 2026-09-25)."""

    def test_phone_metadata_rules_never_force_a_collapsed_row_open(self):
        css = (ROOT / "static/css/components/interactions.css").read_text()
        phone = css.split("Record metadata on a phone", 1)[1].split(
            "PHONE RECORD ACTIONS", 1
        )[0]

        # Whether a row's details show is the accordion's call; a
        # `display: grid !important` here once opened every row on a phone.
        self.assertNotIn("display: grid", phone)
        self.assertNotIn("repeat(2", phone)
        # An opened record's details are one list, one pair per line.
        self.assertIn("flex-direction: column !important", phone)
        # The overview starts at the School ID's edge.
        self.assertIn("grid-column: 1 / -1", phone)

    def test_per_item_accordions_join_a_single_open_group(self):
        script = (ROOT / "static/js/alpine-components.js").read_text()
        self.assertIn("Alpine.directive('accordion'", script)

        groups = {
            "templates/partials/clusters/cluster_card.html": 'x-accordion:clusters="cardExpanded"',
            "templates/partials/projects/project_card.html": 'x-accordion:projects="cardExpanded"',
            "templates/partials/ia/operations.html": 'x-accordion:ia-leaders="open"',
            "templates/partials/ia/_geography_cards.html": 'x-accordion:ia-districts="open"',
            "templates/partials/clusters/oversight_workspace.html": 'x-accordion:cluster-groups="open"',
            "templates/partials/dashboards/cd/map_view.html": 'x-accordion:cd-regions="open"',
        }
        for path, marker in groups.items():
            with self.subTest(path=path):
                self.assertIn(marker, (ROOT / path).read_text())

    def test_native_disclosure_lists_start_closed_and_are_exclusive(self):
        lists = {
            "templates/partials/analytics/target_by_district.html": 'name="analytics-priority-groups"',
            "templates/partials/oversight/portfolio_workspace.html": 'name="portfolio-leads"',
            "templates/partials/priorities/setting_view.html": 'name="priority-milestones"',
            "templates/partials/priorities/team_view.html": 'name="team-delivery"',
            "templates/partials/priorities/distribution_view.html": 'name="ia-mobile-details"',
            "templates/partials/work_plan/detail_tables.html": 'name="work-plan-cost-breakdown"',
        }
        for path, marker in lists.items():
            with self.subTest(path=path):
                template = (ROOT / path).read_text()
                self.assertIn(marker, template)
                self.assertNotIn("{% if forloop.first %}open", template)
                self.assertNotIn("{% if forloop.first %} open", template)

    def test_presence_groups_start_folded_and_open_one_at_a_time(self):
        panel = (ROOT / "templates/partials/dashboards/_whos_online.html").read_text()
        self.assertNotIn("group.open", panel)
        self.assertIn('aria-expanded="false"', panel)
        self.assertIn("if (other !== group) setOpen(other, false)", panel)

    def test_escalation_row_opens_its_own_details(self):
        table = (ROOT / "templates/pages/escalations/_table.html").read_text()
        self.assertIn(
            "closest('a, button, input, select, textarea, label')) "
            "open = open === '{{ e.id }}' ? null",
            table,
        )

    def test_owner_chosen_panels_stay_open_by_default(self):
        # The owner keeps these open (2026-09-25): My Target's sections and
        # a message's Workflow Context are read first, not tapped open.
        my_body = (ROOT / "templates/partials/targets/my_body.html").read_text()
        context = (ROOT / "templates/partials/messages/context_panel.html").read_text()
        self.assertEqual(my_body.count('<details class="edify-disclosure" open>'), 2)
        self.assertIn('x-data="{ ctxOpen: true }"', context)
