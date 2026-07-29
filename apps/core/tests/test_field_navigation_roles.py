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
    def _groups(self, role):
        return {
            group["label"]: group
            for group in build_sidebar_for_user(_user(role), "/dashboard")
        }

    def test_non_field_roles_do_not_receive_schools_and_field(self):
        for role in (CD, RVP, HR, ACCOUNTANT, IA):
            with self.subTest(role=role):
                self.assertNotIn("SCHOOLS & FIELD", self._groups(role))

    def test_field_roles_retain_schools_and_field(self):
        for role in (CCEO, PL, PARTNER, PROJECT_COORDINATOR):
            with self.subTest(role=role):
                self.assertIn("SCHOOLS & FIELD", self._groups(role))

    def test_admin_carries_no_field_workspace(self):
        """Admin was a field-nav role until the Platform Operations split.

        Route authorization is unchanged -- Admin must still be able to OPEN a
        school or an activity to diagnose it -- but a sidebar says what a role's
        work *is*, and Admin's work is the platform. Business pages are reached
        through Team Plans, Support Tickets, Incidents, Search and audit links.
        """
        groups = self._groups(ADMIN)
        self.assertNotIn("SCHOOLS & FIELD", groups)
        self.assertIn("PLATFORM OPERATIONS", groups)
        labels = {i["label"] for i in groups["PLATFORM OPERATIONS"]["items"]}
        self.assertIn("Team Plans", labels)
        self.assertIn("Admin My Plan", labels)

    def test_ia_school_data_workflow_moves_to_verification(self):
        groups = self._groups(IA)

        verification = groups["VERIFICATION"]
        school_directory = [
            item
            for item in verification["items"]
            if item["label"] == "School Directory"
        ]

        self.assertEqual(len(school_directory), 1)
        self.assertEqual(school_directory[0]["url"], "/schools")
        self.assertTrue(school_directory[0]["icon"])

    def test_admin_is_offered_no_school_directory_entry_at_all(self):
        """This used to check the directory appeared once rather than twice for
        Admin. Under Platform Operations it appears in neither group -- the
        duplication question is moot, and what matters now is that no field or
        verification workspace is advertised to Admin."""
        groups = self._groups(ADMIN)

        labels = {item["label"] for group in groups.values() for item in group["items"]}
        self.assertNotIn("School Directory", labels)
        self.assertNotIn("Schools", labels)
