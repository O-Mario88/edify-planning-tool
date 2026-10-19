"""Team and Country Planning Oversight's Analysis lens.

Owner, 2026-10-18: "make sure the existing analytics are integrated into the
profiles and oversights ... CCEO, PL, CD ... and apply the detailed analytics
you built yesterday to all that apply". Team Oversight reads each member of a
team over the schools they hold — their profile's read (`staff_scope`) — and
Country Planning Oversight each Programme Lead over the whole team, their
profile's read (`program_lead_scope`), so a row and its profile never differ.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.analytics import profile_intelligence as engine
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.planning import team_analysis as analysis
from apps.schools.models import School


def _person(email, name, role):
    user = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    return user, StaffProfile.objects.create(user=user, country="Uganda")


class TeamFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = str(get_operational_fy())
        region = Region.objects.create(name="TA Region")
        cls.district = District.objects.create(name="TA District", region=region)
        cls.lead_user, cls.lead = _person(
            "ta-pl@edify.org", "Lena Lead", "Program Lead"
        )
        cls.officer_user, cls.officer = _person(
            "ta-cceo@edify.org", "Otto Officer", "CCEO"
        )
        cls.rival_user, cls.rival = _person(
            "ta-rival@edify.org", "Rita Rival", "Program Lead"
        )
        cls.rival_officer_user, cls.rival_officer = _person(
            "ta-rival-cceo@edify.org", "Rolf Rival", "CCEO"
        )
        cls.director, _ = _person("ta-cd@edify.org", "Dora Director", "CountryDirector")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.lead, supervisee=cls.officer
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.rival, supervisee=cls.rival_officer
        )
        holders = {
            "Lead One": cls.lead.id,
            "Officer One": cls.officer.id,
            "Officer Two": cls.officer.user_id,
            "Rival Officer One": cls.rival_officer.id,
        }
        for index, (name, holder) in enumerate(holders.items()):
            School.objects.create(
                school_id=f"TA-{index}",
                name=f"{name} Primary",
                district=cls.district,
                region=region,
                account_owner_id=holder,
            )

    def named(self, rows):
        return {r["name"]: r for r in rows}


class TeamRowsTest(TeamFixture):
    def test_a_lead_reads_each_member_as_their_profile_does(self):
        rows = self.named(analysis.team_rows(self.lead_user, fy=self.fy))

        officer = rows["Otto Officer"]
        profile = engine.build(engine.staff_scope(self.officer), self.fy)
        self.assertEqual(officer["schools"], 2)
        self.assertEqual(officer["schools"], profile["portfolio"]["schools"])
        self.assertEqual(officer["href"], f"/staff/{self.officer_user.id}?tab=overview")

    def test_the_lead_s_own_row_is_the_schools_they_hold_themselves(self):
        rows = self.named(analysis.team_rows(self.lead_user, fy=self.fy))

        self.assertEqual(rows["Lena Lead (own schools)"]["schools"], 1)
        # The team adds up to its schools, nothing counted twice.
        self.assertEqual(sum(r["schools"] for r in rows.values()), 3)

    def test_a_lead_never_reads_another_team(self):
        rows = self.named(analysis.team_rows(self.lead_user, fy=self.fy))

        self.assertNotIn("Rolf Rival", rows)

    def test_the_country_chooses_the_team_it_reads(self):
        rows = self.named(
            analysis.team_rows(self.director, fy=self.fy, program_lead_id=self.rival.id)
        )

        self.assertEqual(set(rows), {"Rita Rival (own schools)", "Rolf Rival"})

    def test_a_member_holding_nothing_still_has_a_row_reading_0(self):
        """Owner, 2026-10-18: "Leave missing values as 0 for now". A person
        with no school is what an oversight reader looks for, not a row to
        drop."""
        rows = self.named(
            analysis.team_rows(self.director, fy=self.fy, program_lead_id=self.rival.id)
        )

        self.assertEqual(rows["Rita Rival (own schools)"]["schools"], 0)


class LeadRowsTest(TeamFixture):
    def test_each_lead_is_read_as_their_profile_does(self):
        rows = self.named(analysis.lead_rows(self.director, fy=self.fy))

        lead = rows["Lena Lead"]
        profile = engine.build(engine.program_lead_scope(self.lead), self.fy)
        self.assertEqual(lead["schools"], 3)
        self.assertEqual(lead["schools"], profile["portfolio"]["schools"])
        self.assertEqual(rows["Rita Rival"]["schools"], 1)
        self.assertEqual(lead["href"], f"/staff/{self.lead_user.id}?tab=overview")


class LensTest(TeamFixture):
    def test_team_oversight_has_an_analysis_lens(self):
        self.client.force_login(self.lead_user)

        plan = self.client.get("/team-planning-oversight/").content.decode()
        response = self.client.get("/team-planning-oversight/?view=analysis")

        self.assertIn('href="/team-planning-oversight/?view=analysis"', plan)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("data-team-analysis", body)
        self.assertIn("Otto Officer", body)

    def test_country_planning_oversight_has_an_analysis_lens(self):
        self.client.force_login(self.director)

        response = self.client.get("/country-planning-oversight/?view=analysis")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("data-country-analysis", body)
        self.assertIn("Lena Lead", body)
        self.assertIn('href="/country-planning-oversight/?view=analysis"', body)
