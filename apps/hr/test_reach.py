"""The one rule for whose people records a viewer reads (apps.hr.reach)."""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import (
    StaffGeographyAssignment,
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.geography.models import District, Region
from apps.hr.reach import (
    ALL,
    COUNTRIES,
    NONE,
    TEAM,
    people_reach,
    scope_by_country,
    scope_profiles,
)


def _person(email, role, country="Uganda"):
    user = User.objects.create(
        email=email, name=email.split("@")[0], roles=[role], active_role=role
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=email.split("@")[0].upper(), country=country
    )
    return user, profile


class PeopleReachTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uganda = Region.objects.create(name="Reach Uganda", country="Uganda")
        cls.kenya = Region.objects.create(name="Reach Kenya", country="Kenya")
        cls.rwanda = Region.objects.create(name="Reach Rwanda", country="Rwanda")
        cls.kenya_district = District.objects.create(
            name="Reach Nairobi", region=cls.kenya, district_type="primary"
        )
        cls.hr, cls.hr_sp = _person("reach-hr@edify.test", "HumanResources")
        cls.pl, cls.pl_sp = _person("reach-pl@edify.test", "Program Lead")
        cls.cceo, cls.cceo_sp = _person("reach-cceo@edify.test", "CCEO")
        cls.kenyan, cls.kenyan_sp = _person(
            "reach-kenyan@edify.test", "CCEO", country="Kenya"
        )
        cls.rwandan, cls.rwandan_sp = _person(
            "reach-rwandan@edify.test", "CCEO", country="Rwanda"
        )
        cls.cd, cls.cd_sp = _person("reach-cd@edify.test", "CountryDirector")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo_sp
        )

    def _names(self, reach):
        return set(
            scope_profiles(StaffProfile.objects.all(), reach).values_list(
                "user__email", flat=True
            )
        )

    def test_an_unassigned_director_keeps_their_own_country(self):
        reach = people_reach(self.hr)
        self.assertEqual((reach.kind, reach.countries), (COUNTRIES, ("Uganda",)))
        self.assertFalse(reach.assigned)
        self.assertNotIn("reach-kenyan@edify.test", self._names(reach))

    def test_a_director_reads_every_country_their_geography_names(self):
        StaffGeographyAssignment.objects.create(
            staff=self.hr_sp, region_id=self.uganda.id
        )
        # A district assignment names its region's country too.
        StaffGeographyAssignment.objects.create(
            staff=self.hr_sp, district_id=self.kenya_district.id
        )
        reach = people_reach(self.hr)
        self.assertEqual(reach.countries, ("Kenya", "Uganda"))
        self.assertTrue(reach.assigned)
        names = self._names(reach)
        self.assertIn("reach-kenyan@edify.test", names)
        self.assertIn("reach-cceo@edify.test", names)
        self.assertNotIn("reach-rwandan@edify.test", names)
        self.assertEqual(reach.label(), "2 countries")

    def test_a_programme_lead_reads_their_team(self):
        reach = people_reach(self.pl)
        self.assertEqual(reach.kind, TEAM)
        self.assertEqual(
            self._names(reach), {"reach-pl@edify.test", "reach-cceo@edify.test"}
        )

    def test_a_country_director_reads_their_country(self):
        reach = people_reach(self.cd)
        self.assertEqual((reach.kind, reach.countries), (COUNTRIES, ("Uganda",)))

    def test_admin_reads_everything(self):
        admin = User.objects.create(
            email="reach-admin@edify.test",
            name="Admin",
            roles=["Admin"],
            active_role="Admin",
        )
        reach = people_reach(admin)
        self.assertEqual(reach.kind, ALL)
        self.assertIn("Rwanda", reach.filter_options())

    def test_nobody_without_a_record_reads_anything(self):
        stranger = User.objects.create(
            email="reach-none@edify.test",
            name="None",
            roles=["HumanResources"],
            active_role="HumanResources",
        )
        reach = people_reach(stranger)
        self.assertEqual(reach.kind, NONE)
        self.assertEqual(self._names(reach), set())
        self.assertEqual(scope_by_country(StaffProfile.objects.all(), reach).count(), 0)
