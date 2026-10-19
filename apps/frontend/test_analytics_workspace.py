"""What replaced the Analytics workspace.

Every analysis page used to be a section of one Analytics workspace behind one
sidebar door. The entry is retired (owner, 2026-10-19: "Remove the whole
Analytics entry now. Send every section's old link to the closest profile or
oversight page, and give only Reports, Decision Log and Closure Quality their
own sidebar entries"); apps/frontend/test_analytics_retired.py holds the old
links and the three entries. These tests hold the rest in place: the pages
folded away keep no sidebar link of their own, the sidebar's groups stay
readable, and Impact Assessment's own workspace still carries its pages.
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.navigation import (
    IA_SECTIONS,
    PAGE_PERMISSIONS,
    SIDEBAR_ITEMS,
    WORKSPACES,
    build_workspace,
    build_sidebar_for_user,
)
from apps.core.rbac import EdifyRole

# Pages that were folded into other pages. If one of these ever needs a
# sidebar link again that is a product decision, not a refactor — this list is
# where it gets recorded.
MERGED_AWAY_LABELS = {
    "Analytics",
    "Decision Intelligence",
    "SSA Performance",
    "Declining Schools",
    "Core School Health",
    "Impact Analytics",
    "Visit Effectiveness",
    "Analytics Publishing",
    "Completed Archive",
    "HR Analytics",
    # Merged into the Leave workspace.
    "Leave & Coverage",
    "Holidays & Blackouts",
}


def _user(email: str, role: str) -> User:
    user = User.objects.create_user(
        email=email,
        password="password123",
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role, country="Uganda")
    return user


class SidebarStructureTest(TestCase):
    def test_there_is_no_analytics_workspace(self):
        self.assertNotIn("analytics", WORKSPACES)

    def test_merged_pages_no_longer_hold_their_own_sidebar_links(self):
        labels = {
            item["label"] for section in SIDEBAR_ITEMS for item in section["items"]
        }
        self.assertEqual(labels & MERGED_AWAY_LABELS, set())

    def test_single_item_groups_render_as_the_link_itself(self):
        """A collapsed heading over a single link costs a click and reveals
        what the heading already said, so one-link groups are marked standalone
        and the sidebar drops the accordion."""
        for role in (EdifyRole.COUNTRY_DIRECTOR, EdifyRole.COUNTRY_PROGRAM_LEAD):
            user = _user(f"standalone-{role.name.lower()}@door.test", role.value)
            for group in build_sidebar_for_user(user, "/dashboard"):
                with self.subTest(role=role.value, group=group["label"]):
                    self.assertEqual(group["standalone"], len(group["items"]) == 1)
                    if group["standalone"]:
                        # Nothing to expand, so it must not start collapsed.
                        self.assertTrue(group["expanded"])

        lead = _user(
            "standalone-reference@door.test", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        reference = next(
            g
            for g in build_sidebar_for_user(lead, "/dashboard")
            if g["label"] == "REFERENCE"
        )
        # Two links since Closed Schools joined the Programme Lead's sidebar
        # (owner, 2026-09-15), so it is an ordinary group rather than a link.
        self.assertIn("Closed Schools", [i["label"] for i in reference["items"]])
        self.assertFalse(reference["standalone"])

    def test_a_partner_keeps_the_decision_log_by_name(self):
        partner = _user("solo@door.test", EdifyRole.PARTNER_FIELD_OFFICER.value)
        labels = {
            item["label"]
            for group in build_sidebar_for_user(partner, "/dashboard")
            for item in group["items"]
        }
        self.assertIn("Decision Log", labels)
        self.assertNotIn("Analytics", labels)

    def test_the_sub_navigation_stays_off_pages_outside_a_workspace(self):
        client = Client()
        client.force_login(
            _user("render@workspace.test", EdifyRole.COUNTRY_DIRECTOR.value)
        )
        # The Country Director's dashboard is Country Oversight (owner,
        # 2026-09-28): /dashboard sends them there.
        self.assertEqual(
            client.get("/dashboard")["Location"], "/country-planning-oversight/"
        )
        response = client.get("/country-planning-oversight/")
        self.assertEqual(response.status_code, 200)
        # The shared head may name this component in native prefetch rules;
        # what must stay absent is the workspace navigation element itself.
        self.assertNotContains(response, '<nav class="edify-section-nav"')


class IAWorkspaceContractTest(TestCase):
    def setUp(self):
        self.user = _user("ia-workspace@edify.test", EdifyRole.IMPACT_ASSESSMENT.value)
        self.client = Client()
        self.client.force_login(self.user)

    def test_sections_are_distinct_authorized_backend_routes(self):
        # 26 as of 2026-10-19: every Impact Assessment page, clustered by the
        # role description's responsibilities (IA review), where the strip
        # used to carry 11 verification-first sections. Impact Attribution
        # left the strip when it became Programme Learning's Training tab;
        # Country Oversight joined it when the owner gave IA the country lens
        # read-only ("All the team activities but he cannot modify or edit any
        # of the team activities"), and Cluster Oversight and Core School
        # Oversight joined beside it when those pages opened to IA. SSA
        # Performance, Declining Schools, Core School Health, Contribution
        # Analysis and Visit Effectiveness left with the Analytics entry: the
        # oversight pages hold what they read.
        self.assertEqual(len(IA_SECTIONS), 26)
        self.assertEqual(len({s["key"] for s in IA_SECTIONS}), 26)
        self.assertEqual(len({s["url"] for s in IA_SECTIONS}), 26)
        retired = {
            "/ssa",
            "/declining-schools",
            "/core-school-health",
            "/impact",
            "/analytics/visit-effectiveness",
        }
        self.assertEqual({s["url"] for s in IA_SECTIONS} & retired, set())
        for section in IA_SECTIONS:
            with self.subTest(section=section["key"]):
                self.assertIn(section["page_key"], PAGE_PERMISSIONS)
                self.assertIn("IA", PAGE_PERMISSIONS[section["page_key"]])

    def test_shared_analytics_routes_stay_in_the_ia_workspace_for_ia(self):
        for path in ("/ia/dashboard/", "/reports", "/decision-log"):
            with self.subTest(path=path):
                workspace = build_workspace(self.user, path)
                self.assertIsNotNone(workspace)
                self.assertEqual(workspace["key"], "ia")
                self.assertEqual(
                    [s["url"] for s in workspace["sections"] if s["active"]],
                    [path],
                )

    def test_activity_queue_renders_real_url_state_navigation(self):
        response = self.client.get("/ia/verification/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Impact Assessment sections"')
        self.assertContains(response, 'href="/ssa/verification/"')
        # The IA strip is grouped by responsibility (IA review, 2026-09-13):
        # the page shows each group's door and the active group's views.
        self.assertContains(response, "edify-section-nav__cluster")
        self.assertContains(response, 'href="/evidence/"')
        self.assertContains(response, 'aria-current="page"')

    def test_a_shared_page_carries_the_sub_navigation(self):
        """Shared pages remain inside IA's role workspace."""
        for path in ("/reports", "/decision-log"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "edify-section-nav")
                self.assertContains(response, 'href="/ia/verification/"')
                self.assertContains(response, 'href="/evidence/"')
                self.assertNotContains(response, "The analysis workspace")

    def test_sections_are_links_not_tabs(self):
        """Cross-route links described as tabs mislead assistive technology and
        inherit platform.css's in-page tab styling."""
        response = self.client.get("/reports")
        body = response.content.decode()
        nav = body[body.index("edify-section-nav") : body.index("</nav>")]
        self.assertNotIn('role="tab"', nav)
        self.assertNotIn('role="tablist"', nav)


class LeaveWorkspaceTest(TestCase):
    """Your own leave, who covers it, and the calendar it is booked against
    were three sidebar links for one question. They are one workspace now."""

    def test_the_leave_sections_are_offered_together(self):
        from apps.core.navigation import LEAVE_SECTIONS, build_sections

        user = _user("leave@workspace.test", EdifyRole.COUNTRY_DIRECTOR.value)
        keys = [
            s["key"]
            for s in build_sections(LEAVE_SECTIONS, user, "/personal-time-off/")
        ]
        # An approver also gets the team's side of the question: the requests
        # to decide, the balances and who is away (2026-09-13).
        self.assertEqual(
            keys,
            [
                "my_leave",
                "coverage",
                "holidays",
                "approvals",
                "tracker",
                "availability",
            ],
        )

    def test_people_who_approve_no_leave_get_only_their_own_sections(self):
        from apps.core.navigation import LEAVE_SECTIONS, build_sections

        user = _user("leave-cceo@workspace.test", EdifyRole.CCEO.value)
        keys = [
            s["key"]
            for s in build_sections(LEAVE_SECTIONS, user, "/personal-time-off/")
        ]
        self.assertEqual(keys, ["my_leave", "coverage", "holidays"])

    def test_each_leave_page_carries_the_strip(self):
        from apps.core.navigation import build_workspace

        user = _user("leave2@workspace.test", EdifyRole.COUNTRY_DIRECTOR.value)
        for path, expected in [
            ("/personal-time-off/", "my_leave"),
            ("/leave/coverage", "coverage"),
            ("/public-holidays", "holidays"),
        ]:
            with self.subTest(path=path):
                workspace = build_workspace(user, path)
                self.assertIsNotNone(workspace)
                self.assertEqual(workspace["key"], "leave")
                active = [s["key"] for s in workspace["sections"] if s["active"]]
                self.assertEqual(active, [expected])

    def test_a_role_without_coverage_access_is_not_offered_it(self):
        from apps.core.navigation import build_workspace

        coordinator = _user(
            "leave3@workspace.test", EdifyRole.PROJECT_COORDINATOR.value
        )
        workspace = build_workspace(coordinator, "/personal-time-off/")
        self.assertIsNotNone(workspace)
        self.assertNotIn("coverage", [s["key"] for s in workspace["sections"]])

    def test_partners_have_no_leave_workspace_at_all(self):
        from apps.core.navigation import build_workspace

        partner = _user("leave4@workspace.test", EdifyRole.PARTNER_FIELD_OFFICER.value)
        self.assertIsNone(build_workspace(partner, "/personal-time-off/"))
