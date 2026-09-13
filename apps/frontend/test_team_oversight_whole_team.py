"""Team Oversight opens on the whole team (Programme Lead alignment, 2026-09-13).

Leading a team starts from the team: a Programme Lead with no portfolio of
their own opened this page on "My Work" and saw nothing. The officer tabs and
the fund-approval deep link keep working, the export follows whichever tab is
showing, and the School Oversight header links to completed work still missing
its evidence for the readers who may open it.
"""

from __future__ import annotations

from apps.accounts.models import StaffProfile, User
from apps.core.rbac import EdifyRole
from apps.frontend.test_planning_oversight_pages import (
    PL_URL,
    OversightPageFixture,
)

EXPORT_URL = "/team-planning-oversight/export"


class WholeTeamTabTest(OversightPageFixture):
    def test_the_whole_team_tab_comes_first_and_is_the_default(self):
        response = self.as_user(self.pl_user).get(PL_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["owner"], "team")
        keys = [tab["key"] for tab in response.context["tabs"]]
        self.assertEqual(keys[:3], ["team", "mine", self.james.id])
        self.assertContains(response, "Whole team")
        # The officer's work shows without choosing them.
        self.assertContains(response, "Alpha Primary")
        self.assertNotContains(response, "Rival Primary")

    @staticmethod
    def _planned_schools(response) -> set[str]:
        """The schools in the tab's plan groups. The School Oversight section
        below lists the team's flagged schools whichever tab is open, so the
        page's text is not the tab's."""
        return {
            item.school_name
            for group in response.context["groups"]
            for item in group["items"]
        }

    def test_my_work_and_the_officer_tabs_still_narrow(self):
        client = self.as_user(self.pl_user)

        self.assertNotIn(
            "Alpha Primary",
            self._planned_schools(client.get(PL_URL, {"owner": "mine"})),
        )
        self.assertIn(
            "Alpha Primary",
            self._planned_schools(client.get(PL_URL, {"owner": self.james.id})),
        )

    def test_the_fund_approval_link_still_lands_on_that_officer(self):
        """ "View Full Plan" carries the officer's User id."""
        response = self.as_user(self.pl_user).get(
            PL_URL, {"view": "planning", "owner": self.james_user.id}
        )

        self.assertEqual(response.context["owner"], self.james.id)

    def test_the_export_follows_the_tab(self):
        client = self.as_user(self.pl_user)

        whole = b"".join(client.get(EXPORT_URL).streaming_content).decode()
        mine = b"".join(
            client.get(EXPORT_URL, {"owner": "mine"}).streaming_content
        ).decode()

        self.assertIn("Alpha Primary", whole)
        self.assertNotIn("Rival Primary", whole)
        self.assertNotIn("Alpha Primary", mine)


class EvidenceGapsLinkTest(OversightPageFixture):
    def test_the_lead_is_offered_the_evidence_gaps(self):
        self.assertContains(
            self.as_user(self.pl_user).get(PL_URL),
            'href="/evidence/?tab=pending"',
        )

    def test_a_reader_who_cannot_open_the_evidence_centre_is_not(self):
        accountant = User.objects.create(
            email="acct-oversight@t.test",
            name="Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            is_active=True,
        )
        StaffProfile.objects.create(user=accountant, title="Accountant")

        response = self.as_user(accountant).get(PL_URL)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "/evidence/?tab=pending")
