"""The combined Core Trained / Core Graduate / Champion list, and its rules.

Owner, 2026-09-21: the three belong together, take everything a client school
takes, and are never assigned to a partner.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School
from apps.schools.programme_schools import (
    PROGRAMME_SCHOOL_TYPES,
    programme_schools,
    type_options,
)


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="PS Region")
        cls.district = District.objects.create(name="PS District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="PS SC", district=cls.district)
        cls.user = User.objects.create_user(
            email="ps-cceo@edify.org",
            name="PS CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(
            user=cls.user, staff_number="ST-PS", country="Uganda"
        )
        cls.trained = cls._school("PS-TRAINED", "core_trained")
        cls.graduate = cls._school("PS-GRAD", "core_graduate")
        cls.champion = cls._school("PS-CHAMP", "champion")
        cls.client_school = cls._school("PS-CLIENT", "client")
        cls.core = cls._school("PS-CORE", "core")

    @classmethod
    def _school(cls, code, school_type):
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            school_type=school_type,
            account_owner_id=cls.staff.id,
        )
        StaffSchoolAssignment.objects.create(staff=cls.staff, school_id=school.id)
        return school


class TheListIsExactlyTheThreeTypesTest(_Fixture):
    def test_the_three_types_are_listed_and_nothing_else_is(self):
        result = programme_schools(self.user)
        listed = {row.school_id for row in result.rows}
        self.assertEqual(listed, {"PS-TRAINED", "PS-GRAD", "PS-CHAMP"})
        self.assertNotIn("PS-CLIENT", listed)
        self.assertNotIn("PS-CORE", listed)

    def test_the_counts_name_each_type(self):
        result = programme_schools(self.user)
        self.assertEqual(result.total, 3)
        self.assertEqual(
            result.by_type,
            {"core_trained": 1, "core_graduate": 1, "champion": 1},
        )

    def test_the_type_options_are_the_gate_s_own_list(self):
        self.assertEqual(
            [value for value, _label in type_options()],
            list(PROGRAMME_SCHOOL_TYPES),
        )

    def test_filtering_by_type_narrows_the_rows(self):
        result = programme_schools(self.user, school_type="champion")
        self.assertEqual([row.school_id for row in result.rows], ["PS-CHAMP"])

    def test_a_closed_school_leaves_the_list(self):
        School.objects.filter(id=self.champion.id).update(operational_status="closed")
        result = programme_schools(self.user)
        self.assertNotIn("PS-CHAMP", {row.school_id for row in result.rows})


class EveryRowCarriesItsTwoRulesTest(_Fixture):
    def test_each_row_shows_the_client_school_entitlement(self):
        from apps.planning.visit_gate import CLIENT_VISIT_CAP

        for row in programme_schools(self.user).rows:
            self.assertEqual(row.visits_allowed, CLIENT_VISIT_CAP, row.school_id)
            self.assertTrue(row.can_schedule, row.school_id)

    def test_each_row_says_a_partner_can_never_take_it(self):
        for row in programme_schools(self.user).rows:
            self.assertIn("never assigned to a partner", row.partner_reason)


class ThePageRendersForItsReadersTest(_Fixture):
    def test_the_page_opens_and_names_the_rule(self):
        self.client.force_login(self.user)
        response = self.client.get("/programme-schools")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Programme Schools", html)
        self.assertIn("School PS-CHAMP", html)
        self.assertIn("never assigned to a partner", html)
        self.assertNotIn("School PS-CLIENT", html)

    def test_a_partner_cannot_open_it(self):
        partner_user = User.objects.create_user(
            email="ps-partner@edify.org",
            name="PS Partner",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            password="x",
            is_active=True,
        )
        self.client.force_login(partner_user)
        response = self.client.get("/programme-schools")
        self.assertIn(response.status_code, (302, 403))
