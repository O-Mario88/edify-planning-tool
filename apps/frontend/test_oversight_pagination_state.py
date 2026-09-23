"""Paging a table must not change whose table it is.

THE DEFECT (owner, 2026-09-22)

"Oversight keeps taking the Programme Leads back to their page when they click
the next page on the pagination. A PL should be able to use pagination on every
table and reach everything, not loop back to his own plans."

Every oversight workspace puts one person's tables inside a tab panel, and the
tab was a browser-only choice. The pager under the table is a link the SERVER
wrote from the query it was asked with, and following it replaced the whole
query — so page two arrived with the strip back at its first tab: "my-clusters"
on Cluster Oversight, "My Core Schools" on Core School Oversight, the first
group on Team Planning. Every one of those is the Programme Lead's own work.

These tests hold the two halves of the fix: the strip is addressable and
validated (`tabState`), and the pager carries every registered parameter
(`table-pagination.js`). The third is the Country Director's lazily fetched
team panel, whose own URL never carried the page number.
"""

from pathlib import Path

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from apps.core.templatetags.table_pagination import carry_query, tab_values


ROOT = Path(__file__).resolve().parents[2]

WORKSPACES = (
    "templates/partials/oversight/cd_team_detail.html",
    "templates/partials/oversight/cd_workspace.html",
    "templates/partials/oversight/cluster_oversight_workspace.html",
    "templates/partials/oversight/core_schools_oversight_workspace.html",
)


class _Reader:
    active_role = "COUNTRY_PROGRAM_LEAD"
    is_authenticated = True
    name = "Tester"
    id = "u1"


def _request(url):
    request = RequestFactory().get(url)
    request.user = _Reader()
    return request


def _summary():
    return {
        "total_planned": 1,
        "at_risk": 0,
        "planned_budget": 0,
        "staff_scheduled": 0,
        "partner_scheduled": 0,
        "partner_awaiting_schedule": 0,
        "execution_progress": None,
    }


def _leads():
    return [
        {
            "id": "L1",
            "name": "Ann",
            "count": 3,
            "cceo_tabs": [
                {"id": "O1", "name": "Bob", "count": 2, "clusters": [], "schools": []},
                {"id": "O2", "name": "Cara", "count": 1, "clusters": [], "schools": []},
            ],
        },
        {"id": "L2", "name": "Dan", "count": 0, "cceo_tabs": []},
    ]


def _owner_groups():
    return [
        {
            "id": "G1",
            "name": "Ann",
            "items": [],
            "summary": _summary(),
            "page_param": "g1_page",
            "client_school_visits": [],
            "core_school_visits": [],
            "cluster_meetings": [],
            "planned_trainings": [],
            "autoload": False,
        },
        {
            "id": "G2",
            "name": "Bob",
            "items": [],
            "summary": _summary(),
            "page_param": "g2_page",
            "client_school_visits": [],
            "core_school_visits": [],
            "cluster_meetings": [],
            "planned_trainings": [],
            "autoload": True,
        },
    ]


class TabValuesTests(SimpleTestCase):
    def test_lists_the_ids_a_strip_offers(self):
        self.assertEqual(
            tab_values([{"id": "a"}, {"id": "b"}]),
            '["a", "b"]',
        )

    def test_tolerates_objects_and_nothing_at_all(self):
        class Row:
            id = "x"

        self.assertEqual(tab_values([Row()]), '["x"]')
        self.assertEqual(tab_values(None), "[]")

    def test_a_group_with_no_id_is_written_the_way_the_panel_writes_it(self):
        # The country lens folds work nobody leads into an "Unassigned" group
        # with no id, and its panel says `x-show="activeLead === 'None'"`
        # because that is what {{ group.id }} renders. The list has to agree,
        # or that one tab selects nothing.
        self.assertEqual(tab_values([{"id": None}]), '["None"]')


class CarryQueryTests(SimpleTestCase):
    def test_forwards_the_page_a_fragment_must_open_on(self):
        request = RequestFactory().get(
            "/country-planning-oversight/?period=month&fy=2026&lead=L1&g1_page-cv=3"
        )
        self.assertEqual(
            carry_query({"request": request}, "period", "fy"),
            "&lead=L1&g1_page-cv=3",
        )

    def test_empty_without_a_request_or_without_anything_to_carry(self):
        self.assertEqual(carry_query({}, "period"), "")
        self.assertEqual(
            carry_query({"request": RequestFactory().get("/?fy=2026")}, "fy"), ""
        )


class StripsAreAddressableTests(SimpleTestCase):
    """Each strip writes its choice to the URL, through one shared controller."""

    def test_no_workspace_hand_rolls_the_url_write_any_more(self):
        # The hand-rolled `pick` wrote whatever key it was handed onto whatever
        # property it guessed, with no check that the id belonged to this strip.
        # A nested strip could write the parameter of the strip above it, and a
        # Lead opened with another Lead's officer in the URL showed no panel.
        for path in WORKSPACES:
            source = (ROOT / path).read_text()
            with self.subTest(path=path):
                self.assertNotIn("history.replaceState", source)
                self.assertIn("tabState(", source)

    def test_programme_lead_cluster_strip_offers_its_own_ids(self):
        body = render_to_string(
            "partials/oversight/cluster_oversight_workspace.html",
            {
                "request": _request("/team-planning-oversight/?view=clusters"),
                "is_programme_lead": True,
                # The member strip is keyed on `uses_member_tabs` since it
                # also serves a cluster-holding CCEO (2026-09-23); the service
                # sets it for every Programme Lead.
                "uses_member_tabs": True,
                "cceo_tabs": [
                    {
                        "id": "my-clusters",
                        "name": "My clusters",
                        "count": 2,
                        "clusters": [],
                        "schools": 1,
                    },
                    {
                        "id": "O1",
                        "name": "Bob",
                        "count": 1,
                        "clusters": [],
                        "schools": 1,
                    },
                ],
                "leads": [],
                "fy": "2026",
            },
        )
        self.assertIn(
            "tabState('activeOfficer', 'officer', "
            "[&quot;my-clusters&quot;, &quot;O1&quot;], 'my-clusters')",
            body,
        )

    def test_country_cluster_strips_are_nested_and_each_validates_its_own(self):
        body = render_to_string(
            "partials/oversight/cluster_oversight_workspace.html",
            {
                "request": _request("/country-planning-oversight/?view=clusters"),
                "is_programme_lead": False,
                "leads": _leads(),
                "cceo_tabs": [],
                "fy": "2026",
                "selected_program_lead": "",
            },
        )
        self.assertIn("[&quot;L1&quot;, &quot;L2&quot;]", body)
        # The officer strip under Ann offers Ann's officers and nobody else's,
        # so Dan's panel cannot be opened onto one of them.
        self.assertIn("[&quot;O1&quot;, &quot;O2&quot;]", body)

    def test_core_school_strips_offer_their_own_ids(self):
        lead_body = render_to_string(
            "partials/oversight/core_schools_oversight_workspace.html",
            {
                "request": _request("/team-planning-oversight/"),
                "is_programme_lead": True,
                "cceo_tabs": [
                    {
                        "id": "me",
                        "name": "Me",
                        "count": 1,
                        "completed": 0,
                        "schools": [],
                        "tab_label": "My Core Schools",
                        "heading": "My Core Schools",
                    },
                    {
                        "id": "O1",
                        "name": "Bob",
                        "count": 1,
                        "completed": 0,
                        "schools": [],
                    },
                ],
                "leads": [],
                "fy": "2026",
            },
        )
        self.assertIn(
            "tabState('activeCceo', 'cceo', [&quot;me&quot;, &quot;O1&quot;], 'me')",
            lead_body,
        )

    def test_team_detail_officer_strip_offers_the_groups_on_the_page(self):
        body = render_to_string(
            "partials/oversight/cd_team_detail.html",
            {
                "request": _request("/team-planning-oversight/?owner=all&officer=G2"),
                "owner_groups": _owner_groups(),
                "program_lead_name": "Ann",
            },
        )
        self.assertIn(
            "tabState('activeOfficer', 'officer', [&quot;G1&quot;, &quot;G2&quot;], 'G1')",
            body,
        )


class CountryTeamFragmentTests(SimpleTestCase):
    """The Country Director's team panel is fetched; it must be fetched whole."""

    def test_the_unassigned_fold_is_a_tab_that_can_be_selected(self):
        groups = _owner_groups() + [
            {
                "id": None,
                "name": "Unassigned",
                "items": [],
                "summary": _summary(),
                "page_param": "g3_page",
                "autoload": False,
            }
        ]
        body = render_to_string(
            "partials/oversight/cd_workspace.html",
            {**self._context(groups, "G1"), "groups": groups},
        )
        # What the panel compares against, and what the strip offers, agree.
        self.assertIn("x-show=\"activeLead === 'None'\"", body)
        self.assertIn("&quot;None&quot;", body)

    def _body(self, url, selected_lead):
        groups = _owner_groups()
        for group in groups:
            group["autoload"] = group["id"] == selected_lead
        return render_to_string(
            "partials/oversight/cd_workspace.html",
            {**self._context(groups, selected_lead, url=url), "groups": groups},
        )

    def _context(self, groups, selected_lead, url="/country-planning-oversight/"):
        return {
            "request": _request(url),
            "groups": groups,
            "selected_lead": selected_lead,
            "summary": _summary(),
            "kpis": [],
            "period": "month",
            "fy": "2026",
            "week": "",
            "selected_month": "9",
            "selected_quarter": "",
            "period_label": "September",
            "may_delegate": True,
            "advanced": {},
            "filter_options": {},
            "fy_options": [],
            "program_leads": [],
            "cluster_oversight": {},
            "lens_tabs": [],
            "team_progress": [],
        }

    def test_the_team_named_in_the_url_is_the_team_that_opens(self):
        body = self._body("/country-planning-oversight/?lead=G2", "G2")
        second = body.split('id="team-detail-2"', 1)[1][:900]
        first = body.split('id="team-detail-1"', 1)[1][:900]
        self.assertIn('hx-trigger="load"', second)
        self.assertIn('hx-trigger="load-team"', first)

    def test_the_fragment_is_asked_for_the_page_the_reader_chose(self):
        body = self._body("/country-planning-oversight/?lead=G2&g1_page-cv=3", "G2")
        # Without this the panel came back at page one whatever the link said,
        # because the fragment's own URL carried period and financial year and
        # nothing else.
        self.assertIn("&amp;lead=G2&amp;g1_page-cv=3", body)
        self.assertIn("data-pager-fragment=", body)


class PagerCarriesTabStateTests(SimpleTestCase):
    def test_the_page_loads_the_script_that_carries_it(self):
        base = (ROOT / "templates/base.html").read_text()
        self.assertIn("js/table-pagination.js", base)

    def test_a_strip_registers_its_parameter_for_the_pager_to_carry(self):
        components = (ROOT / "static/js/alpine-components.js").read_text()
        self.assertIn("__edifyUrlViewParams", components)
        pager = (ROOT / "static/js/table-pagination.js").read_text()
        self.assertIn("__edifyUrlViewParams", pager)
