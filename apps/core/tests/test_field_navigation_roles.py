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
        self.assertEqual(groups["DAILY"]["items"][0]["label"], "Assigned Schools")

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
        daily = self._groups(ADMIN)["DAILY"]["items"]
        urls = [item["url"] for item in daily]
        self.assertEqual(
            urls[:4], ["/dashboard", "/todos", "/admin-panel/users", "/uploads"]
        )
        weekly = [item["url"] for item in self._groups(ADMIN)["WEEKLY"]["items"]]
        self.assertEqual(weekly[:2], ["/admin-panel/roles-permissions", "/data-repair"])
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

    def test_groups_run_from_most_to_least_visited(self):
        from apps.core.nav_cadence import TIERS

        for role in (ADMIN, CCEO, CD, PL, IA, HR, ACCOUNTANT, PARTNER):
            with self.subTest(role=role):
                labels = [g["label"] for g in build_sidebar_for_user(_user(role), "/")]
                self.assertEqual(labels, [t for t in TIERS if t in labels])
                self.assertEqual(labels[0], "DAILY")
