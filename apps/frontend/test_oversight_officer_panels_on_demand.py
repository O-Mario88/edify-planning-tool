"""Planning Oversight draws only the officer being viewed (owner, 2026-10-26:
"draw only the officer being viewed").

Opening a Programme Lead's team on the country lens built and drew every
officer's four tables, then hid all but one: 3.8 MB and ten seconds on
production for a team of seven. Now the shown officer's panel is drawn and
each other officer's panel is fetched when its tab is picked, from that
officer's own work rather than the whole country's. A panel fetched is the
panel the page would have drawn.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from unittest import mock

from apps.accounts.models import StaffSchoolAssignment, StaffSupervisorAssignment
from apps.core.rbac import EdifyRole
from apps.frontend.test_planning_oversight_pages import OversightPageFixture
from apps.planning import oversight_service as oversight

TEAM_URL = "/team-planning-oversight/"


class _Element(HTMLParser):
    """The text inside the element with a given id."""

    def __init__(self, element_id):
        super().__init__()
        self.element_id = element_id
        self.depth = 0
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            self.depth += 1
        elif dict(attrs).get("id") == self.element_id:
            self.depth = 1

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth and data.strip():
            self.text.append(data.strip())


def element_text(html: str, element_id: str) -> list[str]:
    parser = _Element(element_id)
    parser.feed(html)
    return parser.text


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text: list[str] = []

    def handle_data(self, data):
        if data.strip():
            self.text.append(data.strip())


def fragment_text(html: str) -> list[str]:
    parser = _Text()
    parser.feed(html)
    return parser.text


class TwoOfficerTeam(OversightPageFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.mary_user, cls.mary = cls._staff("mary@t.test", "Mary", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(supervisee=cls.mary, supervisor=cls.pl)
        cls.beta = cls._school("s3", "Beta Primary")
        StaffSchoolAssignment.objects.create(staff=cls.mary, school_id=cls.beta.id)
        cls.mary_activity = cls._activity(cls.mary, cls.beta, cost=30_000)

    def page(self, **params):
        query = {"program_lead": self.pl.id, **params}
        response = self.as_user(self.ia_user).get(TEAM_URL, query)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def panel_index(self, body: str, officer_id: str) -> str:
        found = re.search(
            rf"officer={officer_id}&amp;officer_panel=1&amp;officer_index=(\d+)", body
        )
        self.assertIsNotNone(found, "no on-demand panel for the officer")
        return found.group(1)


class OnlyTheShownOfficerIsDrawn(TwoOfficerTeam):
    def test_the_other_officers_panel_is_only_a_placeholder(self):
        body = self.page(officer=self.james.id)
        james = self.panel_index_of_drawn(body)
        mary = self.panel_index(body, self.mary.id)

        self.assertIn("Alpha Primary", element_text(body, f"officer-panel-{james}"))
        self.assertEqual(
            element_text(body, f"officer-panel-{mary}"),
            ["Loading Mary\u2019s work\u2026"],
        )

    def panel_index_of_drawn(self, body: str) -> str:
        found = re.search(
            r'x-show="activeOfficer[^"]*"\s+id="officer-panel-(\d+)"', body
        )
        self.assertIsNotNone(found, "no officer panel drawn in place")
        return found.group(1)

    def test_the_strip_still_counts_every_officers_work(self):
        body = self.page(officer=self.james.id)

        self.assertIn("Mary", body)
        self.assertIn("team-officer-tab", body)


class APanelIsFetchedWhenItsTabIsPicked(TwoOfficerTeam):
    def _fetched(self, officer, index):
        response = self.as_user(self.ia_user).get(
            TEAM_URL,
            {
                "program_lead": self.pl.id,
                "officer": officer.id,
                "officer_panel": "1",
                "officer_index": index,
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_fetched_panel_is_the_panel_the_page_draws(self):
        index = self.panel_index(self.page(officer=self.james.id), self.mary.id)

        fetched = self._fetched(self.mary, index)
        drawn = self.page(officer=self.mary.id)

        self.assertIn("Beta Primary", fetched)
        self.assertNotIn("Alpha Primary", fetched)
        self.assertEqual(
            fragment_text(fetched), element_text(drawn, f"officer-panel-{index}")
        )

    def test_the_panel_reads_only_that_officers_work(self):
        index = self.panel_index(self.page(officer=self.james.id), self.mary.id)
        calls = []
        real = oversight.build_items

        def recording(*args, **kwargs):
            calls.append(kwargs)
            return real(*args, **kwargs)

        with mock.patch.object(oversight, "build_items", recording):
            self._fetched(self.mary, index)

        self.assertEqual(len(calls), 1)
        self.assertIn(str(self.mary.id), calls[0]["owner_ids"])
        self.assertNotIn(str(self.james.id), calls[0]["owner_ids"])


class OneOfficersBuildIsTheirShareOfTheCountrys(TwoOfficerTeam):
    def test_owner_ids_give_exactly_that_officers_items(self):
        ids = {str(self.mary.id), str(self.mary_user.id)}
        everyone = oversight.build_items(self.ia_user, fy=self.fy)
        mine = oversight.build_items(self.ia_user, fy=self.fy, owner_ids=ids)

        def shape(items):
            return [
                (i.activity_id, i.supervising_pl_id, i.planned_cost, i.risks)
                for i in items
            ]

        expected = [i for i in everyone if str(i.operational_owner_id) in ids]
        self.assertTrue(expected)
        self.assertEqual(shape(mine), shape(expected))
