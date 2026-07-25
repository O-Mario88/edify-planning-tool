"""The Analytics workspace: one sidebar door, many analysis sections.

Every analysis page in the platform used to carry its own sidebar link. They
are now sections of a single workspace, switched between with the
sub-navigation the shell renders. These tests hold that consolidation in
place: the sections stay reachable, permission still decides what each role is
offered, and no analysis page quietly loses its way back into the product.
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.navigation import (
    ANALYTICS_SECTIONS,
    PAGE_PERMISSIONS,
    SIDEBAR_ITEMS,
    build_analytics_sections,
    build_sidebar_for_user,
    get_user_role_slug,
)
from apps.core.rbac import EdifyRole

# The pages that were folded into the workspace. If one of these ever needs a
# sidebar link again that is a product decision, not a refactor — this list is
# where it gets recorded.
MERGED_AWAY_LABELS = {
    "Decision Intelligence",
    "SSA Performance",
    "Declining Schools",
    "Core School Health",
    "Impact Analytics",
    "Visit Effectiveness",
    "Analytics Publishing",
    "Reports",
    "Decision Log",
    "Completed Archive",
    "HR Analytics",
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


class AnalyticsWorkspaceStructureTest(TestCase):
    def test_every_section_declares_a_real_permission_key(self):
        for section in ANALYTICS_SECTIONS:
            with self.subTest(section=section["key"]):
                self.assertIn(section["page_key"], PAGE_PERMISSIONS)
                self.assertTrue(PAGE_PERMISSIONS[section["page_key"]])

    def test_section_keys_and_urls_are_unique(self):
        keys = [s["key"] for s in ANALYTICS_SECTIONS]
        urls = [s["url"] for s in ANALYTICS_SECTIONS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(urls), len(set(urls)))

    def test_merged_pages_no_longer_hold_their_own_sidebar_links(self):
        labels = {
            item["label"] for section in SIDEBAR_ITEMS for item in section["items"]
        }
        self.assertEqual(labels & MERGED_AWAY_LABELS, set())

    def test_the_sidebar_offers_exactly_one_analytics_door(self):
        for role in EdifyRole:
            user = _user(f"{role.name.lower()}@door.test", role.value)
            sections = build_analytics_sections(user, "/dashboard")
            hub_items = [
                item
                for group in build_sidebar_for_user(user, "/dashboard")
                for item in group["items"]
                if item["url"] in {s["url"] for s in sections}
            ]
            with self.subTest(role=role.value):
                if sections:
                    self.assertEqual(len(hub_items), 1)
                    # It opens the first section the role can actually reach.
                    self.assertEqual(hub_items[0]["url"], sections[0]["url"])
                else:
                    self.assertEqual(hub_items, [])

    def test_single_item_groups_render_as_the_link_itself(self):
        """The workspace left QUALITY & INSIGHTS holding one entry. A collapsed
        heading over a single link costs a click and reveals what the heading
        already said, so those groups are marked standalone and the sidebar
        drops the accordion."""
        user = _user("standalone@door.test", EdifyRole.COUNTRY_DIRECTOR.value)
        groups = build_sidebar_for_user(user, "/dashboard")
        for group in groups:
            with self.subTest(group=group["label"]):
                self.assertEqual(group["standalone"], len(group["items"]) == 1)
                if group["standalone"]:
                    # Nothing to expand, so it must not start collapsed.
                    self.assertTrue(group["expanded"])

        analytics = next(g for g in groups if g["label"] == "QUALITY & INSIGHTS")
        self.assertTrue(analytics["standalone"])

    def test_a_role_with_one_section_gets_that_section_by_name(self):
        """An "Analytics" link that opens a single page is a lie about scope."""
        partner = _user("solo@door.test", EdifyRole.PARTNER_FIELD_OFFICER.value)
        sections = build_analytics_sections(partner, "/dashboard")
        labels = {
            item["label"]
            for group in build_sidebar_for_user(partner, "/dashboard")
            for item in group["items"]
        }
        if len(sections) == 1:
            self.assertIn(sections[0]["label"], labels)
            self.assertNotIn("Analytics", labels)
        else:
            self.assertIn("Analytics", labels)


class AnalyticsWorkspaceScopingTest(TestCase):
    def test_sections_offered_match_the_role_permission_map_exactly(self):
        for role in EdifyRole:
            user = _user(f"{role.name.lower()}@scope.test", role.value)
            slug = get_user_role_slug(user)
            offered = {s["key"] for s in build_analytics_sections(user, "/dashboard")}
            entitled = {
                s["key"]
                for s in ANALYTICS_SECTIONS
                if slug in PAGE_PERMISSIONS[s["page_key"]]
            }
            with self.subTest(role=role.value):
                self.assertEqual(offered, entitled)

    def test_every_offered_section_actually_opens(self):
        client = Client()
        for role in EdifyRole:
            user = _user(f"{role.name.lower()}@open.test", role.value)
            client.force_login(user)
            for section in build_analytics_sections(user, "/dashboard"):
                with self.subTest(role=role.value, section=section["key"]):
                    response = client.get(section["url"])
                    self.assertEqual(
                        response.status_code,
                        200,
                        f"{role.value} was offered {section['url']} "
                        f"but got {response.status_code}",
                    )
            client.logout()


class AnalyticsWorkspaceActiveStateTest(TestCase):
    def setUp(self):
        self.admin = _user("active@state.test", EdifyRole.ADMIN.value)

    def test_exactly_one_section_is_active_on_each_section_page(self):
        for section in ANALYTICS_SECTIONS:
            url = section["url"]
            with self.subTest(url=url):
                active = [
                    s["label"]
                    for s in build_analytics_sections(self.admin, url)
                    if s["active"]
                ]
                self.assertEqual(active, [section["label"]])

    def test_publishing_highlights_on_its_canonical_url(self):
        """It was registered with a trailing slash the route does not use, so
        prefix matching never matched and the link never lit up."""
        active = [
            s["key"]
            for s in build_analytics_sections(self.admin, "/analytics/publishing")
            if s["active"]
        ]
        self.assertEqual(active, ["publishing"])

    def test_the_generic_analytics_url_stays_owned_by_overview(self):
        """A role_urls override adds a destination, it does not close the
        generic one. /analytics is a real page for a Program Lead whose
        Overview points at /analytics/program-lead — and when it matched no
        section, the sub-navigation vanished on the page the workspace is
        named after."""
        for role in (
            EdifyRole.COUNTRY_PROGRAM_LEAD,
            EdifyRole.COUNTRY_DIRECTOR,
            EdifyRole.PROJECT_COORDINATOR,
        ):
            user = _user(f"{role.name.lower()}@generic.test", role.value)
            role_url = build_analytics_sections(user, "/dashboard")[0]["url"]
            self.assertNotEqual(role_url, "/analytics")
            with self.subTest(role=role.value):
                for path in ("/analytics", role_url):
                    active = [
                        s["key"]
                        for s in build_analytics_sections(user, path)
                        if s["active"]
                    ]
                    self.assertEqual(active, ["overview"], f"path {path}")

    def test_nested_non_analytics_routes_do_not_claim_a_section(self):
        # /ssa/upload/ is the IA upload centre, not SSA Performance.
        for path in ("/ssa/upload/", "/dashboard", "/schools"):
            with self.subTest(path=path):
                self.assertEqual(
                    [
                        s["label"]
                        for s in build_analytics_sections(self.admin, path)
                        if s["active"]
                    ],
                    [],
                )


class AnalyticsWorkspaceRenderTest(TestCase):
    def setUp(self):
        self.user = _user("render@workspace.test", EdifyRole.COUNTRY_DIRECTOR.value)
        self.client = Client()
        self.client.force_login(self.user)

    def test_the_sub_navigation_renders_on_a_section_page(self):
        response = self.client.get("/impact")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "edify-section-nav")
        self.assertContains(response, 'aria-label="Analytics sections"')
        # Sibling sections are offered as real links.
        self.assertContains(response, 'href="/declining-schools"')
        self.assertContains(response, 'aria-current="page"')

    def test_the_sub_navigation_stays_off_pages_outside_the_workspace(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "edify-section-nav")

    def test_the_overview_page_carries_the_sub_navigation(self):
        """The generic /analytics URL is a real page for roles whose Overview
        points elsewhere, and it is the page the workspace is named after — it
        must offer the same way around as every other section. One navigation,
        not a strip plus a duplicate grid of the same links below it."""
        for path in ("/analytics", "/analytics/country-director"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "edify-section-nav")
                self.assertContains(response, 'href="/analytics/visit-effectiveness"')
                self.assertNotContains(response, "The analysis workspace")

    def test_sections_are_links_not_tabs(self):
        """Cross-route links described as tabs mislead assistive technology and
        inherit platform.css's in-page tab styling."""
        response = self.client.get("/impact")
        body = response.content.decode()
        nav = body[body.index("edify-section-nav") : body.index("</nav>")]
        self.assertNotIn('role="tab"', nav)
        self.assertNotIn('role="tablist"', nav)
