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
        for role in (CCEO, PL, PROJECT_COORDINATOR):
            with self.subTest(role=role):
                self.assertIn("SCHOOLS & FIELD", self._groups(role))

    def test_partner_gets_my_field_work_instead(self):
        """Partners left SCHOOLS & FIELD (2026-08-20): their surface is the
        MY FIELD WORK intake — Assigned Schools/Activities, Evidence and
        Completed & Payments — never the staff school directory."""
        groups = self._groups(PARTNER)
        self.assertNotIn("SCHOOLS & FIELD", groups)
        self.assertIn("MY FIELD WORK", groups)
        labels = {i["label"] for i in groups["MY FIELD WORK"]["items"]}
        self.assertEqual(
            labels,
            {
                "Assigned Schools",
                "Assigned Activities",
                "Evidence",
                "Completed & Payments",
            },
        )

    def test_admin_carries_both_the_platform_and_field_workspaces(self):
        """Admin was narrowed to Platform Operations, then widened again.

        The reason is operational rather than architectural: at Edify the
        person holding Admin also works the field as a CCEO, and a sidebar that
        advertised none of it made the field half of their job unreachable
        without switching roles for every action.

        Navigation is not authorization, and this is why the distinction is
        worth stating: Admin is offered the field workspace and still cannot
        verify an activity, disburse against a budget, or approve a team fund
        plan -- see test_admin_platform_boundary, which pins those three to
        their owning roles. Showing someone a queue is not letting them act on
        it.
        """
        groups = self._groups(ADMIN)
        self.assertIn("SCHOOLS & FIELD", groups)
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

    def test_admin_is_offered_the_school_directory_exactly_once(self):
        """The original defect this test was written for, which the field
        workspace coming back makes live again: Admin could be offered School
        Directory from two different groups at once, so the same page appeared
        twice in one sidebar.
        """
        groups = self._groups(ADMIN)

        labels = [item["label"] for group in groups.values() for item in group["items"]]
        self.assertIn("School Directory", labels)
        self.assertEqual(
            labels.count("School Directory"),
            1,
            "one page, one sidebar entry -- two groups both offering it is the "
            "duplication this test exists to catch",
        )
        duplicates = {label for label in labels if labels.count(label) > 1}
        self.assertEqual(
            duplicates,
            set(),
            f"no sidebar entry may appear twice for Admin, found: {duplicates}",
        )
