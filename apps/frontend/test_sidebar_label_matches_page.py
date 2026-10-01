"""A sidebar link and the page it opens say the same name (2026-10-01).

The audit of that date opened every sidebar destination for every role and
found 28 of 130 whose link and page disagreed: "Planning Oversight" opened a
page headed "Team Oversight", "Quality Flags" opened "Quality Checks", "Cost
Settings" opened "Cost Catalogue", and "Notification centre" opened
"Notifications Center". A person who has just pressed a link reads the heading
to confirm they arrived; two names for one place make them check twice.

The rule is deliberately loose about wording and strict about identity: every
word of the shorter name must appear in the longer one, so "Leave Tracker" may
open "Team Leave & Coverage Tracker" and "Extra Work" may open "Extra Assigned
Work", but neither may open a page that never says "Tracker" or "Work".
"""

from __future__ import annotations

import re

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.navigation import build_sidebar_for_user

#: The staff roles whose sidebars are walked. Partner and MFI accounts need an
#: organisation behind them to open anything and carry a dozen links between
#: them; they are covered by their own portal tests.
ROLES = (
    "Admin",
    "CountryDirector",
    "Program Lead",
    "CCEO",
    "HumanResources",
    "ImpactAssessment",
    "Accountant",
    "RegionalVicePresident",
    "RegionalProgramLead",
    "ProjectCoordinator",
)

#: Links that are allowed to open a page with another heading, and why. Add to
#: this only with a reason a reader would accept; the default answer to a
#: mismatch is to rename one side.
EXEMPT: dict[str, str] = {
    # A workspace entry opens the first page of a strip and the strip names
    # the pages (partials/_section_nav.html); the heading is the page's.
    "/actions/sent": "PL 'Team Assignments' is the Actions Sent / Extra Work strip",
    "/leave/approvals": "PL 'Team Leave' is the leave approvals strip",
    "/cce-leadership/feedback": "PL 'Regional Lead' is the collaboration strip",
    "/performance-reviews": "PL 'Team Performance' is the reviews strip",
    "/mfi-portal/loans": "MFI portal sections share the portal heading and a strip",
    "/mfi-portal/monthly-return": "MFI portal sections share the portal heading",
    "/mfi-portal/data-issues": "MFI portal sections share the portal heading",
    "/mfi-portal/reports": "MFI portal sections share the portal heading",
    # The performance agreement opens on its Priorities tab; the page is being
    # reworked with the Coordinator's "My Performance" fold (owner,
    # 2026-09-30) and takes its name there.
    "/my-performance": "opens on the agreement's Priorities tab",
}

#: The same, for a link whose URL other roles reach under the page's own name.
EXEMPT_LABELS: dict[tuple[str, str], str] = {
    # The Project Coordinator's Budget, Weekly Advance and Work Plan are one
    # "Finance" entry with a strip (NAV_FOLDS, owner 2026-09-30).
    ("Finance", "/budget"): "PC 'Finance' is the budget / advance / work plan strip",
    ("My Performance", "/priorities"): "PC 'My Performance' is the priorities strip",
}

_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[a-z0-9]+")
#: Words that carry no identity: "My Plan" may open "Plan", "Users" may open
#: "User Management".
_FILLER = {"my", "the", "and", "of", "for", "a", "dashboard"}


def _words(text: str) -> set[str]:
    words = set()
    for word in _WORD.findall(text.lower().replace("&amp;", " ")):
        if word in _FILLER:
            continue
        # One stem for a name and its plural: Loans/Loan, Priorities/Priority.
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("s") and not word.endswith("ss") and len(word) > 3:
            word = word[:-1]
        words.add(word)
    return words


def _same_place(label: str, headings: list[str]) -> bool:
    wanted = _words(label)
    if not wanted:
        return True
    for heading in headings:
        said = _words(heading)
        if said and (wanted <= said or said <= wanted):
            return True
    return False


class SidebarLabelMatchesPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = []
        for index, role in enumerate(ROLES):
            user = User.objects.create_user(
                email=f"label-parity-{index}@edify.org",
                password="password123",
                name=f"Label Parity {index}",
                roles=[role],
                active_role=role,
            )
            StaffProfile.objects.create(
                user=user,
                title=role,
                department="Programmes",
                country="Uganda",
                onboarding_state="active",
            )
            cls.users.append(user)

    def test_the_word_rule_reads_names_the_way_a_person_does(self):
        self.assertTrue(_same_place("Leave Tracker", ["Team Leave & Coverage Tracker"]))
        self.assertTrue(_same_place("Loans", ["Loan dashboard"]))
        self.assertTrue(_same_place("Priorities", ["Uganda Master Priority Plan"]))
        self.assertTrue(_same_place("My Plan", ["Start your day", "My Plan"]))
        self.assertFalse(_same_place("Planning Oversight", ["Team Oversight"]))
        self.assertFalse(_same_place("Quality Flags", ["Quality Checks"]))
        self.assertFalse(_same_place("Cost Settings", ["Cost Catalogue"]))

    def test_every_sidebar_link_opens_a_page_that_says_its_name(self):
        seen: set[str] = set()
        checked = 0
        mismatches = []
        for user in self.users:
            client = Client()
            client.force_login(user)
            for section in build_sidebar_for_user(user, "/"):
                for item in section["items"]:
                    url, label = item["url"], item["label"]
                    key = f"{label}|{url}"
                    if key in seen or url in EXEMPT or (label, url) in EXEMPT_LABELS:
                        continue
                    seen.add(key)
                    # A role's home is "Dashboard" whatever the page behind it
                    # is called for that role.
                    if label == "Dashboard":
                        continue
                    response = client.get(url)
                    if response.status_code != 200:
                        continue
                    headings = [
                        " ".join(_TAG.sub(" ", raw).split())
                        for raw in _H1.findall(response.content.decode())
                    ]
                    if not headings:
                        mismatches.append(f"{label!r} -> {url}: no <h1>")
                        continue
                    checked += 1
                    if not _same_place(label, headings):
                        mismatches.append(
                            f"{label!r} -> {url}: page says {headings!r} "
                            f"({user.active_role})"
                        )
        # A floor, so the walk cannot pass by opening nothing.
        self.assertGreaterEqual(checked, 80, f"only {checked} pages were read")
        self.assertEqual(mismatches, [], "\n" + "\n".join(mismatches))
