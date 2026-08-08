"""Team oversight is one page, and partner work is one page.

Two pairs answered the same question from two sidebar entries. "Team Planning"
showed a team's plans while §12 also asked for their flagged schools; "Partners"
and "Partner Oversight" both showed which schools were with which partner, who
had scheduled and what it cost, and a supervisor had no way to know which of
the two to trust.

The merges are held here rather than in the nav module because a sidebar entry
is not the thing that makes two pages one — the routing and the content are.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.planning.flagged_schools import team_flagged_schools
from apps.schools.models import School


class OversightFixture(TestCase):
    def setUp(self):
        self.fy = get_operational_fy()
        self.region = Region.objects.create(name="Merge Region")
        self.district = District.objects.create(
            name="Merge District", region=self.region
        )
        self.pl, self.pl_profile = self._staff(
            "pl@merge.test", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        self.cceo, self.cceo_profile = self._staff("cceo@merge.test", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_profile, supervisor=self.pl_profile
        )

    def _staff(self, email, role):
        user = User.objects.create_user(
            email=email,
            name=email.split("@")[0],
            roles=[role.value],
            active_role=role.value,
            password="pwd",
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title=role.value)

    def _school(self, ref, owner):
        school = School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            region=self.region,
            district=self.district,
            school_type="client",
            account_owner_id=owner.id,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.create(staff=owner, school_id=school.id)
        return school

    def _planned(self, school, owner, *, when=None):
        """A school planned this month with no SSA — the top flag."""
        when = when or date.today().replace(day=1)
        return Activity.objects.create(
            activity_type="school_visit",
            school_id=school.id,
            responsible_staff_id=owner.id,
            fy=self.fy,
            status="planned",
            planned_date=when,
        )


class FlaggedSchoolsAreTheThirdLensOnOneTeamTest(OversightFixture):
    def test_a_lead_sees_a_supervised_cceos_flagged_school(self):
        school = self._school("MERGE-FLAG", self.cceo_profile)
        self._planned(school, self.cceo_profile)

        result = team_flagged_schools(self.pl, fy=self.fy, month=date.today().month)

        self.assertEqual(result["total"], 1)
        owners = {g["owner_name"] for g in result["groups"]}
        self.assertIn("cceo@merge.test".split("@")[0], owners)

    def test_it_is_grouped_by_owner_because_the_next_move_is_a_conversation(self):
        """One row per school scattered down a list is not what a supervisor
        acts on; "this person has four" is."""
        for i in range(3):
            school = self._school(f"MERGE-G{i}", self.cceo_profile)
            self._planned(school, self.cceo_profile)

        result = team_flagged_schools(self.pl, fy=self.fy, month=date.today().month)

        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(result["groups"][0]["count"], 3)

    def test_another_leads_team_is_not_included(self):
        stranger, stranger_profile = self._staff("stranger@merge.test", EdifyRole.CCEO)
        school = self._school("MERGE-STRANGER", stranger_profile)
        self._planned(school, stranger_profile)

        result = team_flagged_schools(self.pl, fy=self.fy, month=date.today().month)

        self.assertEqual(result["total"], 0)

    def test_a_delegated_school_stays_listed_and_is_marked(self):
        """The dashboard card hides these — it is an unassigned queue and
        hiding stops two people sending the same action. Oversight wants the
        opposite: "somebody is on it" answers half the questions this page
        gets asked."""
        from django.utils import timezone

        from apps.planning.action_models import ActionState, TeamAction

        school = self._school("MERGE-DELEGATED", self.cceo_profile)
        self._planned(school, self.cceo_profile)
        TeamAction.objects.create(
            school_id=school.id,
            fy=self.fy,
            state=ActionState.OPEN,
            condition_key=f"{school.id}:no_ssa:{self.fy}",
            detected_at=timezone.now(),
        )

        result = team_flagged_schools(self.pl, fy=self.fy, month=date.today().month)

        self.assertEqual(result["total"], 1)
        self.assertTrue(result["groups"][0]["rows"][0]["delegated"])
        self.assertEqual(result["groups"][0]["delegated"], 1)

    def test_the_section_renders_on_the_team_oversight_page(self):
        school = self._school("MERGE-PAGE", self.cceo_profile)
        self._planned(school, self.cceo_profile)
        self.client.force_login(self.pl)

        response = self.client.get("/team-planning-oversight/")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("School Oversight", body)
        self.assertIn("Flagged schools", body)

    def test_the_section_carries_nothing_submittable(self):
        """§12: team oversight opens an oversight record, never an editable
        school page. Structural, not cosmetic — the partial has no form."""
        source = open(
            "templates/partials/oversight/flagged_schools.html", encoding="utf8"
        ).read()

        self.assertNotIn("<form", source)
        self.assertNotIn("hx-post", source)
        self.assertNotIn("csrf_token", source)


class PartnerWorkIsOnePageTest(OversightFixture):
    def test_a_lead_asking_for_partners_lands_on_partner_oversight(self):
        self.client.force_login(self.pl)

        response = self.client.get("/partners")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/partner-oversight/", response["Location"])

    def test_a_cceo_lands_there_too(self):
        self.client.force_login(self.cceo)

        response = self.client.get("/partners")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/partner-oversight/", response["Location"])

    def test_a_partner_organisation_keeps_its_own_workspace(self):
        """The redirect is conditional for a reason: Partner Oversight does not
        admit Partner roles, so sending everyone would leave the external
        organisations with no directory at all."""
        partner_user = User.objects.create_user(
            email="officer@merge.test",
            name="Partner Officer",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            password="pwd",
            is_active=True,
        )
        Partner.objects.create(
            name="Merge Partner", user=partner_user, active_status=True
        )
        self.client.force_login(partner_user)

        response = self.client.get("/partners")

        self.assertEqual(response.status_code, 200)

    def test_a_role_without_oversight_access_is_not_bounced_into_a_refusal(self):
        """HR holds `partners` and not `partner_oversight`. A blanket redirect
        would have sent them to a page that then denied them."""
        hr, _ = self._staff("hr@merge.test", EdifyRole.HUMAN_RESOURCES)
        self.client.force_login(hr)

        response = self.client.get("/partners")

        self.assertEqual(response.status_code, 200)
