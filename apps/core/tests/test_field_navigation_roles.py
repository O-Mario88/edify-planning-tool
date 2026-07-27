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
        for role in (CCEO, PL, PARTNER, PROJECT_COORDINATOR, ADMIN):
            with self.subTest(role=role):
                self.assertIn("SCHOOLS & FIELD", self._groups(role))

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

    def test_school_directory_is_not_duplicated_for_admin(self):
        groups = self._groups(ADMIN)

        verification_labels = {
            item["label"] for item in groups["VERIFICATION"]["items"]
        }
        field_labels = {item["label"] for item in groups["SCHOOLS & FIELD"]["items"]}

        self.assertNotIn("School Directory", verification_labels)
        self.assertIn("Schools", field_labels)
