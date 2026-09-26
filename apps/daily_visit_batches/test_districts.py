"""district_type_for_staff: whose visit it is decides the district type.

School visit costing spec, 2026-09-26: field staff (a CCEO or a Program Lead)
are primary only in the one district on their profile; head-office staff are
primary in the Kampala, Wakiso and Mukono zone and secondary anywhere else,
whatever their profile says. The district's own classification answers only
when there is nobody to resolve for, or a field profile has no primary
district yet.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.rbac import EdifyRole
from apps.daily_visit_batches.districts import (
    HQ_PRIMARY_DISTRICTS,
    district_type_for_staff,
)
from apps.geography.models import District, Region


class DistrictTypeForStaffTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Resolution Region")
        cls.kampala = District.objects.create(
            name="Kampala", region=cls.region, district_type="primary"
        )
        # Spelt as the register might; classified the old way as secondary.
        cls.wakiso = District.objects.create(
            name="wakiso", region=cls.region, district_type="secondary"
        )
        cls.gulu = District.objects.create(
            name="Gulu", region=cls.region, district_type="secondary"
        )
        cls.jinja = District.objects.create(name="Jinja", region=cls.region)

    def _staff(self, email, role, primary=None):
        user = User.objects.create_user(
            email=email,
            name=email,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        profile = StaffProfile.objects.create(
            user=user, title=role, primary_district_id=primary.id if primary else None
        )
        return user, profile

    def test_the_zone_is_kampala_wakiso_and_mukono(self):
        self.assertEqual(HQ_PRIMARY_DISTRICTS, ("Kampala", "Wakiso", "Mukono"))

    def test_head_office_is_primary_in_the_zone_and_secondary_beyond_it(self):
        for role in (
            EdifyRole.COUNTRY_DIRECTOR.value,
            EdifyRole.IMPACT_ASSESSMENT.value,
            EdifyRole.PROGRAM_ACCOUNTANT.value,
            EdifyRole.ADMIN.value,
        ):
            with self.subTest(role=role):
                user, profile = self._staff(f"{role.lower()}@hq.test", role)
                for who in (user.id, profile.id):
                    self.assertEqual(
                        district_type_for_staff(who, self.kampala), "primary"
                    )
                    # The zone answers by name; the old classification said secondary.
                    self.assertEqual(
                        district_type_for_staff(who, self.wakiso), "primary"
                    )
                    self.assertEqual(
                        district_type_for_staff(who, self.gulu), "secondary"
                    )
                    # ... and where the old classification was blank.
                    self.assertEqual(
                        district_type_for_staff(who, self.jinja), "secondary"
                    )

    def test_a_head_office_profile_district_does_not_move_the_zone(self):
        user, _ = self._staff(
            "cd-gulu@hq.test", EdifyRole.COUNTRY_DIRECTOR.value, primary=self.gulu
        )
        self.assertEqual(district_type_for_staff(user.id, self.gulu), "secondary")
        self.assertEqual(district_type_for_staff(user.id, self.kampala), "primary")

    def test_field_staff_are_primary_only_in_their_own_district(self):
        cceo, cceo_profile = self._staff(
            "cceo-gulu@field.test", EdifyRole.CCEO.value, primary=self.gulu
        )
        for who in (cceo.id, cceo_profile.id):
            self.assertEqual(district_type_for_staff(who, self.gulu), "primary")
            self.assertEqual(district_type_for_staff(who, self.kampala), "secondary")
            self.assertEqual(district_type_for_staff(who, self.wakiso), "secondary")
            self.assertEqual(district_type_for_staff(who, self.jinja), "secondary")
        lead, _ = self._staff(
            "pl-kampala@field.test",
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            primary=self.kampala,
        )
        self.assertEqual(district_type_for_staff(lead.id, self.kampala), "primary")
        self.assertEqual(district_type_for_staff(lead.id, self.wakiso), "secondary")

    def test_a_field_profile_without_a_primary_district_keeps_the_old_answer(self):
        """The spec requires one; until it is set the day prices as it did."""
        user, _ = self._staff("cceo-unset@field.test", EdifyRole.CCEO.value)
        self.assertEqual(district_type_for_staff(user.id, self.kampala), "primary")
        self.assertEqual(district_type_for_staff(user.id, self.gulu), "secondary")
        self.assertIsNone(district_type_for_staff(user.id, self.jinja))

    def test_nobody_to_resolve_for_keeps_the_old_answer(self):
        self.assertEqual(district_type_for_staff(None, self.kampala), "primary")
        self.assertEqual(district_type_for_staff("nobody", self.gulu), "secondary")
        self.assertIsNone(district_type_for_staff("nobody", self.jinja))

    def test_no_district_is_home(self):
        self.assertEqual(district_type_for_staff("anyone", None), "primary")
