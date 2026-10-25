"""Country readers land on Country Oversight; everyone else on Home.

Owner, 2026-10-25: "IA and Country Director, RVP and Regional Program Lead
homepage dashboard should be Country Oversight by default". Signing in had
opened Home for every role since 2026-10-24 (#294).
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.permissions import RolePermissionService
from apps.core.rbac import EdifyRole

COUNTRY_OVERSIGHT = "/country-planning-oversight/"
COUNTRY_READERS = (
    EdifyRole.IMPACT_ASSESSMENT,
    EdifyRole.COUNTRY_DIRECTOR,
    EdifyRole.REGIONAL_VICE_PRESIDENT,
)


class CountryOversightLandingTest(TestCase):
    def _user(self, role, password="Secret-1!"):
        user = User.objects.create(
            email=f"{role.value.lower()}@land.test",
            name=role.value,
            roles=[role.value],
            active_role=role.value,
            is_active=True,
        )
        user.set_password(password)
        user.save()
        StaffProfile.objects.create(user=user, title=role.value)
        return user

    def test_the_four_country_readers_land_on_country_oversight(self):
        for role in COUNTRY_READERS:
            with self.subTest(role=role.value):
                user = self._user(role)
                self.assertTrue(
                    RolePermissionService.can_view_page(
                        user, "country_planning_oversight"
                    )
                )
                self.client.force_login(user)
                for path in ("/", "/login"):
                    self.assertEqual(
                        self.client.get(path)["Location"], COUNTRY_OVERSIGHT
                    )

    def test_signing_in_opens_country_oversight(self):
        user = self._user(EdifyRole.IMPACT_ASSESSMENT)
        response = self.client.post(
            "/login", {"email": user.email, "password": "Secret-1!"}
        )
        self.assertEqual(response["Location"], COUNTRY_OVERSIGHT)

    def test_a_listed_role_without_the_page_lands_on_home(self):
        # The Regional Programme Lead is on the owner's list but does not
        # hold Country Oversight (a country-wide page; their lens is a
        # region): Home, never an access-denied page, until they are given it.
        user = self._user(EdifyRole.REGIONAL_PROGRAM_LEAD)
        self.assertFalse(
            RolePermissionService.can_view_page(user, "country_planning_oversight")
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get("/")["Location"], "/home")

    def test_everyone_else_still_lands_on_home(self):
        for role in (EdifyRole.COUNTRY_PROGRAM_LEAD, EdifyRole.CCEO):
            with self.subTest(role=role.value):
                self.client.force_login(self._user(role))
                self.assertEqual(self.client.get("/")["Location"], "/home")

    def test_finishing_the_required_documents_lands_there_too(self):
        from apps.documents.views import _next_blocking_destination

        user = self._user(EdifyRole.COUNTRY_DIRECTOR)
        self.assertEqual(_next_blocking_destination(user), COUNTRY_OVERSIGHT)
