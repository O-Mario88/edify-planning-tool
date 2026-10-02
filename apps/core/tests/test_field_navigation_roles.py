from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.core.navigation import (
    ACCOUNTANT,
    ADMIN,
    CCEO,
    CD,
    HR,
    IA,
    PARTNER,
    PL,
    PROJECT_COORDINATOR,
    RVP,
    build_sidebar_for_user,
)


def _user(role):
    return SimpleNamespace(is_authenticated=True, active_role=role)


class FieldNavigationRoleTest(SimpleTestCase):
    """Which field doors each role is offered. Since 2026-09-14 the sidebar is
    grouped by how often pages are visited (apps.core.nav_cadence), so these
    pin the pages a role reaches rather than the group they sit in."""

    def _groups(self, role):
        return {
            group["label"]: group
            for group in build_sidebar_for_user(_user(role), "/dashboard")
        }

    def _links(self, role, path="/dashboard"):
        return [
            (item["label"], item["url"])
            for group in build_sidebar_for_user(_user(role), path)
            for item in group["items"]
        ]

    def test_non_field_roles_do_not_receive_the_field_workspace(self):
        for role in (CD, RVP, HR, ACCOUNTANT, IA):
            with self.subTest(role=role):
                urls = {url for _label, url in self._links(role)}
                self.assertNotIn("/core-schools", urls)
                # Closed Schools is a record the CD and IA read (owner,
                # 2026-09-15); the other non-field roles still do not.
                if role not in (CD, IA):
                    self.assertNotIn("/schools/closed", urls)

    def test_field_roles_retain_schools_and_field(self):
        for role in (CCEO, PL, PROJECT_COORDINATOR):
            with self.subTest(role=role):
                labels = {label for label, _url in self._links(role)}
                self.assertIn("Planning", labels)
                self.assertTrue("Schools" in labels or "School Directory" in labels)

    def test_country_director_reaches_the_cluster_directory(self):
        """The CD holds `clusters` with country scope, so /clusters lists every
        cluster for them in the same card directory a CCEO or PL opens."""
        for role in (CD, CCEO, PL):
            with self.subTest(role=role):
                links = self._links(role)
                self.assertEqual(links.count(("Clusters", "/clusters")), 1)

    def test_clusters_is_offered_once_per_sidebar(self):
        """Admin's audience override must not turn the CD-only registration
        into a second Clusters link."""
        for role in (ADMIN, CD, CCEO, PL):
            with self.subTest(role=role):
                labels = [label for label, _url in self._links(role, "/clusters")]
                self.assertEqual(labels.count("Clusters"), 1)

    def test_partner_gets_their_field_work_instead(self):
        """Partners work their assigned schools and activities, never the staff
        school directory, and their day starts on Assigned Schools."""
        groups = self._groups(PARTNER)
        labels = {label for label, _url in self._links(PARTNER)}
        self.assertNotIn("Schools", labels)
        for label in (
            "Assigned Schools",
            "Assigned Activities",
            "Evidence",
            "Completed & Payments",
        ):
            with self.subTest(label=label):
                self.assertIn(label, labels)
        self.assertEqual(groups["MY WORK"]["items"][0]["label"], "Assigned Schools")

    def test_admin_carries_both_the_platform_and_field_workspaces(self):
        """Admin also works the field as a CCEO, so it is offered both the
        platform operations pages and the field workspace. Navigation is not
        authorization: see test_admin_platform_boundary."""
        labels = {label for label, _url in self._links(ADMIN)}
        for label in ("Team Plans", "Admin My Plan", "Planning"):
            with self.subTest(label=label):
                self.assertIn(label, labels)
        self.assertTrue("Schools" in labels or "School Directory" in labels)

    def test_admin_finds_users_and_upload_center_at_the_top(self):
        """Admin's own administration opens the sidebar: the visit-frequency
        regroup had left Users and Upload Center deep in a fifty-link WEEKLY
        group where the owner could not find them (2026-09-15)."""
        # Grouped by subject since 2026-10-02: they stay in the first, open
        # group, and the rest of the administration has a group of its own.
        mine = self._groups(ADMIN)["MY WORK"]["items"]
        urls = [item["url"] for item in mine]
        self.assertEqual(
            urls[:4], ["/dashboard", "/todos", "/admin-panel/users", "/uploads"]
        )
        admin = {item["url"] for item in self._groups(ADMIN)["ADMINISTRATION"]["items"]}
        self.assertLessEqual({"/admin-panel/roles-permissions", "/data-repair"}, admin)
        # User administration is not offered to IA or the field roles.
        for role in (IA, PL, CCEO, PARTNER):
            with self.subTest(role=role):
                urls = {url for _label, url in self._links(role)}
                self.assertNotIn("/admin-panel/users", urls)

    def test_ia_reaches_the_school_directory_once(self):
        """IA creates and validates school records without being a field role."""
        links = [
            item
            for group in build_sidebar_for_user(_user(IA), "/dashboard")
            for item in group["items"]
            if item["url"] == "/schools"
        ]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["label"], "School Directory")
        self.assertTrue(links[0]["icon"])

    def test_admin_is_offered_the_school_directory_exactly_once(self):
        """One page, one sidebar entry: Admin was once offered the directory
        from two groups at once."""
        links = self._links(ADMIN)
        self.assertEqual(sum(1 for _label, url in links if url == "/schools"), 1)
        labels = [label for label, _url in links]
        duplicates = {label for label in labels if labels.count(label) > 1}
        self.assertEqual(duplicates, set())

    def test_groups_run_in_subject_order_and_start_with_the_persons_own_work(self):
        """Groups by what a page is about (owner, 2026-10-02), always in the
        order apps.core.nav_groups names them, the person's own work first."""
        from apps.core.nav_groups import GROUPS

        for role in (ADMIN, CCEO, CD, PL, IA, HR, ACCOUNTANT, PARTNER):
            with self.subTest(role=role):
                labels = [g["label"] for g in build_sidebar_for_user(_user(role), "/")]
                self.assertEqual(labels, [g for g in GROUPS if g in labels])
                self.assertEqual(labels[0], "MY WORK")

    def test_no_group_is_a_heading_over_one_page(self):
        """A lone page joins a neighbouring group rather than sitting under a
        heading of its own (nav_groups.LONE_PAGE_JOINS)."""
        for role in (ADMIN, CCEO, CD, PL, IA, HR, ACCOUNTANT, PARTNER):
            with self.subTest(role=role):
                for group in build_sidebar_for_user(_user(role), "/"):
                    if group["label"] != "MY WORK":
                        self.assertGreater(len(group["items"]), 1, group["label"])

    def test_every_registered_page_has_a_subject_group(self):
        """A page with no group would land in My Work by default, silently."""
        from apps.core.nav_groups import PAGE_GROUP
        from apps.core.navigation import SIDEBAR_ITEMS

        registered = {
            item["page_key"] for section in SIDEBAR_ITEMS for item in section["items"]
        }
        self.assertEqual(sorted(registered - set(PAGE_GROUP)), [])
