"""A signed-in account with no staff profile can open its own PD page.

A Professional Development allocation belongs to a StaffProfile, and not every
account has one — an Admin, or anyone invited before HR has finished setting
them up. `_staff()` has always been able to return None and `allocation_history`
has always handled it, but `get_or_create_allocation`, `balances` and
`get_page` read `sp.id` regardless, so those people got a 500 on their own page.

Found by the route crawl, which walks every argument-free page as every role.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.professional_development.services import StaffPDService


def _user(email: str, role: str):
    return get_user_model().objects.create_user(
        email=email,
        password="password123",
        name="No Profile",
        roles=[role],
        active_role=role,
        is_active=True,
    )


class NoStaffProfileTest(TestCase):
    def setUp(self):
        self.user = _user("no-profile@pd.test", EdifyRole.CCEO.value)
        self.client = Client()
        self.client.force_login(self.user)

    def test_the_page_opens_instead_of_raising(self):
        response = self.client.get("/my-professional-development")
        self.assertEqual(response.status_code, 200)

    def test_it_says_why_it_is_empty(self):
        """Four zeroes with no explanation reads as a broken page."""
        body = self.client.get("/my-professional-development").content.decode()
        self.assertIn("Your staff profile is not set up yet", body)

    def test_the_balances_are_zero_and_labelled_as_such(self):
        balances = StaffPDService.balances(self.user, get_operational_fy())
        self.assertFalse(balances["has_staff_profile"])
        self.assertEqual(balances["annual_allocation"], 0)
        self.assertEqual(balances["remaining"], 0)

    def test_no_allocation_row_is_invented(self):
        """get_or_create would otherwise write a row keyed on a staff id that
        does not exist."""
        self.assertIsNone(
            StaffPDService.get_or_create_allocation(self.user, get_operational_fy())
        )

    def test_the_export_does_not_raise_either(self):
        response = self.client.get("/my-professional-development/export")
        self.assertLess(response.status_code, 500)
